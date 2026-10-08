from fake_bpy import FakeKeyframePoints, FakeObject, NS, fake_bpy

from shuvi_blender_agent import ErrorCode, Request, Status
from shuvi_blender_agent.animation import AnimationOperations
from shuvi_blender_agent.animation_pose import PoseBoneAnimationOperations
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.rigging import RiggingOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.verification import compare as real_compare


class FakePoseBone:
    def __init__(self, name):
        self.name = name
        self.rotation_mode = "XYZ"
        self.location = [0.0, 0.0, 0.0]
        self.rotation_euler = [0.0, 0.0, 0.0]
        self.rotation_quaternion = [1.0, 0.0, 0.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]
        self.constraints = []
        self.owner = None

    def path_from_id(self, property_name):
        return f'pose.bones["{self.name}"].{property_name}'

    def keyframe_insert(self, data_path, frame):
        obj = self.owner
        if obj.animation_data is None:
            action = NS(name=obj.name + "PoseAction", users=1, fcurves=[])
            obj.animation_data = NS(action=action, action_slot=None, drivers=[], nla_tracks=[])
        full_path = self.path_from_id(data_path)
        curves = obj.animation_data.action.fcurves
        for index, value in enumerate(getattr(self, data_path)):
            curve = next(
                (
                    item
                    for item in curves
                    if item.data_path == full_path and item.array_index == index
                ),
                None,
            )
            if curve is None:
                curve = NS(
                    data_path=full_path,
                    array_index=index,
                    keyframe_points=FakeKeyframePoints(),
                    update=lambda: None,
                )
                curves.append(curve)
            point = curve.keyframe_points.insert(float(frame), float(value))
            point.interpolation = "BEZIER"
        return True

    def keyframe_delete(self, data_path, frame):
        obj = self.owner
        if obj.animation_data is None:
            return False
        full_path = self.path_from_id(data_path)
        removed = False
        curves = obj.animation_data.action.fcurves
        for curve in list(curves):
            if curve.data_path != full_path:
                continue
            for point in list(curve.keyframe_points):
                if abs(float(point.co[0]) - float(frame)) < 1e-5:
                    curve.keyframe_points.remove(point)
                    removed = True
            if not curve.keyframe_points:
                curves.remove(curve)
        return removed


def rig_bone(name):
    return NS(
        name=name,
        parent=None,
        head_local=[0.0, 0.0, 0.0],
        tail_local=[0.0, 0.0, 1.0],
        matrix_local=None,
        use_connect=False,
        use_deform=True,
        inherit_scale="FULL",
    )


def setup():
    obj = FakeObject("AnimatedRig", "ARMATURE")
    obj.data = NS(
        name="AnimatedRigData",
        users=0,
        library=None,
        bones=[rig_bone("Root")],
    )
    root = FakePoseBone("Root")
    root.owner = obj
    obj.pose = NS(bones=[root])

    bpy = fake_bpy([obj])
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    animation = AnimationOperations(objects)
    rigging = RiggingOperations(objects)
    pose_animation = PoseBoneAnimationOperations(animation, rigging)
    registry = ToolRegistry(
        [*animation.tools(), *pose_animation.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, obj, root, inspector, animation, rigging, registry


def target(inspector, obj):
    snapshot = inspector.snapshot(obj)
    return {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }


def pose_inspect(registry, object_id):
    result = registry.dispatch(
        Request(
            "animation.pose_bone_inspect",
            {"object_id": object_id, "bone_name": "Root"},
        )
    )
    assert result.status == Status.SUCCEEDED
    return result.data


def insert_payload(inspector, obj, state, frame=10, **overrides):
    payload = {
        "target": target(inspector, obj),
        "expected_rig_revision": state["rig_revision"],
        "expected_animation_revision": state["animation_revision"],
        "bone_name": "Root",
        "frame": frame,
        "location": [1.0, 2.0, 3.0],
        "rotation_mode": "XYZ",
        "rotation": [0.1, 0.2, 0.3],
        "scale": [1.0, 1.0, 1.0],
        "interpolation": "LINEAR",
    }
    payload.update(overrides)
    return payload


def test_m5_pose_bone_inspect_reports_empty_bounded_state():
    _, obj, _, inspector, _, _, registry = setup()
    state = pose_inspect(registry, inspector.snapshot(obj)["object_id"])

    assert state["bone_name"] == "Root"
    assert state["channel_count"] == 0
    assert state["expected_channel_count"] == 9
    assert state["point_count"] == 0
    assert state["unique_frames"] == []
    assert state["managed_mutation_ready"] is True
    assert state["raw_pose_channels_only"] is True
    assert state["source_only"] is True
    assert state["real_runtime_verified"] is False
    assert len(state["pose_animation_revision"]) == 64


def test_m5_insert_xyz_pose_keyframe_with_exact_channel_readback():
    _, obj, _, inspector, _, _, registry = setup()
    before = pose_inspect(registry, inspector.snapshot(obj)["object_id"])
    result = registry.dispatch(
        Request(
            "animation.pose_bone_keyframe_insert",
            insert_payload(inspector, obj, before),
        )
    )

    assert result.status == Status.VERIFIED
    after = pose_inspect(registry, before["object_id"])
    assert after["managed_session_action"] is True
    assert after["channel_count"] == 9
    assert after["expected_channel_count"] == 9
    assert after["point_count"] == 9
    assert after["unique_frames"] == [10.0]
    assert after["animation_revision"] != before["animation_revision"]
    assert after["rig_revision"] != before["rig_revision"]
    assert all(
        point["interpolation"] == "LINEAR"
        for channel in after["channels"]
        for point in channel["points"]
    )


def test_m5_insert_quaternion_pose_keyframe_normalizes_rotation():
    _, obj, root, inspector, _, _, registry = setup()
    before = pose_inspect(registry, inspector.snapshot(obj)["object_id"])
    result = registry.dispatch(
        Request(
            "animation.pose_bone_keyframe_insert",
            insert_payload(
                inspector,
                obj,
                before,
                rotation_mode="QUATERNION",
                rotation=[1.0, 1.0, 0.0, 0.0],
                interpolation="BEZIER",
            ),
        )
    )

    assert result.status == Status.VERIFIED
    after = pose_inspect(registry, before["object_id"])
    assert after["rotation_mode"] == "QUATERNION"
    assert after["channel_count"] == 10
    assert after["point_count"] == 10
    assert root.rotation_quaternion[0] == root.rotation_quaternion[1]
    assert round(sum(value * value for value in root.rotation_quaternion), 8) == 1.0


def test_m5_duplicate_frame_and_foreign_action_fail_closed():
    _, obj, root, inspector, _, _, registry = setup()
    before = pose_inspect(registry, inspector.snapshot(obj)["object_id"])
    first = registry.dispatch(
        Request(
            "animation.pose_bone_keyframe_insert",
            insert_payload(inspector, obj, before),
        )
    )
    assert first.status == Status.VERIFIED

    fresh = pose_inspect(registry, before["object_id"])
    duplicate = registry.dispatch(
        Request(
            "animation.pose_bone_keyframe_insert",
            insert_payload(inspector, obj, fresh),
        )
    )
    assert duplicate.status == Status.FAILED
    assert duplicate.error.code == ErrorCode.AMBIGUOUS_TARGET

    _, obj2, root2, inspector2, _, _, registry2 = setup()
    root2.keyframe_insert("location", 5)
    foreign = pose_inspect(registry2, inspector2.snapshot(obj2)["object_id"])
    assert "FOREIGN_ACTION" in foreign["blockers"]
    denied = registry2.dispatch(
        Request(
            "animation.pose_bone_keyframe_insert",
            insert_payload(inspector2, obj2, foreign, frame=10),
        )
    )
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.SAFETY_DENIED


def test_m5_stale_animation_revision_fails_with_fresh_target_and_rig_revision():
    _, obj, _, inspector, _, _, registry = setup()
    before = pose_inspect(registry, inspector.snapshot(obj)["object_id"])
    first = registry.dispatch(
        Request(
            "animation.pose_bone_keyframe_insert",
            insert_payload(inspector, obj, before),
        )
    )
    assert first.status == Status.VERIFIED
    fresh = pose_inspect(registry, before["object_id"])

    payload = insert_payload(inspector, obj, fresh, frame=20)
    payload["expected_animation_revision"] = before["animation_revision"]
    stale = registry.dispatch(
        Request("animation.pose_bone_keyframe_insert", payload)
    )

    assert stale.status == Status.FAILED
    assert stale.error.code == ErrorCode.STALE_STATE


def test_m5_verification_failure_rolls_back_pose_and_new_action(monkeypatch):
    _, obj, root, inspector, _, _, registry = setup()
    before = pose_inspect(registry, inspector.snapshot(obj)["object_id"])
    original_pose = {
        "location": list(root.location),
        "rotation_mode": root.rotation_mode,
        "rotation_euler": list(root.rotation_euler),
        "scale": list(root.scale),
    }
    calls = {"count": 0}

    def fail_once(expected, actual):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_compare({"forced": 1}, {"forced": 2})
        return real_compare(expected, actual)

    monkeypatch.setattr("shuvi_blender_agent.animation_pose.compare", fail_once)
    result = registry.dispatch(
        Request(
            "animation.pose_bone_keyframe_insert",
            insert_payload(inspector, obj, before),
        )
    )

    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    restored = pose_inspect(registry, before["object_id"])
    assert restored["animation_revision"] == before["animation_revision"]
    assert restored["rig_revision"] == before["rig_revision"]
    assert obj.animation_data is None
    assert root.location == original_pose["location"]
    assert root.rotation_mode == original_pose["rotation_mode"]
    assert root.rotation_euler == original_pose["rotation_euler"]
    assert root.scale == original_pose["scale"]
