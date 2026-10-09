"""Level 9 M6: independent, typed AREA lamp region targeting (source only)."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.studio_lighting import RigPreview, StudioLightingOperations
from shuvi_blender_agent.tools import ToolRegistry


def setup(preset="PRODUCT_FIVE_POINT"):
    subject = FakeObject("TargetSubject", "MESH")
    subject.location = [2.0, 3.0, 4.0]
    subject.dimensions = [2.0, 4.0, 6.0]
    bpy = fake_bpy([subject])
    inspector = BpyInspector(bpy)
    snapshot = inspector.snapshot(subject)
    target = {
        "object_id": snapshot["object_id"],
        "expected_name": snapshot["name"],
        "expected_revision": snapshot["revision"],
    }
    reg = ToolRegistry(
        StudioLightingOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    args = {
        "subject": target,
        "name_prefix": "TargetRig",
        "preset": preset,
        "distance_scale": 3.5,
        "intensity_scale": 1.0,
        "mood": "TEAL_AMBER",
        "shadow_profile": "SOFT_CINEMATIC",
    }
    return bpy, subject, inspector, reg, args


def preview(reg, data):
    result = reg.dispatch(Request("lighting.studio_preview", data))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(reg, data, plan):
    return reg.dispatch(
        Request(
            "lighting.studio_apply",
            data | {"expected_lighting_revision": plan["lighting_revision"]},
        )
    )


def release(reg, token):
    return reg.dispatch(Request("lighting.studio_release", {"expected_lighting_token": token}))


def test_m6_independently_aim_each_lamp_at_real_subject_regions():
    bpy, subject, inspector, reg, data = setup()
    offsets = {
        "Key": [0.35, -0.2, 0.3],
        "Fill": [-0.2, 0.25, -0.1],
        "Top": [0.1, 0.0, 0.45],
        "Edge": [-0.35, 0.1, 0.0],
    }
    plan_central = preview(reg, data)
    before = inspector.summary()["revision"]
    new = data | {"target_offsets": offsets}
    plan = preview(reg, new)
    assert plan["lighting_revision"] != plan_central["lighting_revision"]
    assert plan["ready"]
    assert plan["target_offsets"] == offsets
    by_role = {row["role"]: row for row in plan["lights"]}
    plain = {row["role"]: row for row in plan_central["lights"]}
    assert by_role["Key"]["aim_point"] == [
        2.0 + 2.0 * 0.35,
        3.0 + 4.0 * -0.2,
        4.0 + 6.0 * 0.3,
    ]
    assert by_role["Key"]["location"] == plain["Key"]["location"]
    assert by_role["Key"]["rotation_euler"] != plain["Key"]["rotation_euler"]
    assert by_role["Rim"]["rotation_euler"] == plain["Rim"]["rotation_euler"]
    assert inspector.summary()["revision"] == before
    done = apply(reg, new, plan)
    assert done.status == Status.VERIFIED, done.error
    for entry in plan["lights"]:
        obj = bpy.data.objects.get(entry["name"])
        assert list(obj.rotation_euler) == entry["rotation_euler"]
        assert list(obj.location) == entry["location"]
    freed = release(reg, done.data["lighting_token"])
    assert freed.status == Status.VERIFIED, freed.error
    assert bpy.context.scene.objects == [subject]
    assert inspector.summary()["revision"] == before


def test_m6_changed_target_after_preview_is_stale_without_mutation():
    bpy, _, _, reg, data = setup()
    old = data | {"target_offsets": {"Key": [0.2, 0, 0]}}
    planned = preview(reg, old)
    new = data | {"target_offsets": {"Key": [0.25, 0, 0]}}
    outcome = apply(reg, new, planned)
    assert outcome.error.code == ErrorCode.STALE_STATE
    assert not bpy.data.lights


@pytest.mark.parametrize(
    "target_offsets",
    [
        {"Unknown": [0, 0, 0]},
        {"Key": [0.5, 0, 0]},
        {"Key": [True, 0, 0]},
        {"Key": [float("inf"), 0, 0]},
        {"Key": [0, 0]},
        {"Key": "x"},
        [],
        {"Key": [0, 0, 0], "Extra": [0, 0, 0]},
    ],
)
def test_m6_strict_invalid_role_or_offsets_fail_closed(target_offsets):
    _, _, _, _, data = setup("SOFT_STUDIO")
    with pytest.raises(AgentError):
        RigPreview.parse(data | {"target_offsets": target_offsets})


def test_m6_targeted_light_corruption_rolls_back_entire_rig():
    bpy, subject, inspector, reg, data = setup("BEAUTY_CLAMSHELL")
    desired = data | {"target_offsets": {"Catchlight": [-0.2, 0.3, 0.1]}}
    plan = preview(reg, desired)
    before = inspector.summary()["revision"]
    count = {"n": 0}

    def corrupt_once():
        count["n"] += 1
        if count["n"] == 1:
            bpy.data.objects.get("TargetRig_Catchlight").rotation_euler = [0.0, 0.0, 0.0]

    bpy.context.view_layer.update = corrupt_once
    result = apply(reg, desired, plan)
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert bpy.context.scene.objects == [subject]
    assert not bpy.data.lights
    assert inspector.summary()["revision"] == before


def test_m6_extra_roles_only_supported_for_relevant_preset():
    _, _, _, _, data = setup("SOFT_STUDIO")
    with pytest.raises(AgentError):
        RigPreview.parse(data | {"target_offsets": {"Catchlight": [0, 0, 0]}})
    alternate = RigPreview.parse(
        data | {"preset": "BEAUTY_CLAMSHELL", "target_offsets": {"Catchlight": [0, 0, 0]}}
    )
    assert alternate.target_offsets["Catchlight"] == (0.0, 0.0, 0.0)
