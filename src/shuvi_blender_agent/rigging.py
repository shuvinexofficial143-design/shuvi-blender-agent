"""Level 6 rigging: bounded inspection, armature creation and hierarchy editing."""

from dataclasses import dataclass
from math import isfinite

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import bounded_text, revision
from .models import ObjectTarget, Transform, object_name, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, invalid, string
from .verification import compare

MAX_RIG_BONES = 256
MAX_POSE_CONSTRAINTS_PER_BONE = 64
MAX_POSE_CONSTRAINTS = 512
MAX_BONE_COORDINATE = 100_000


@dataclass(frozen=True)
class ArmatureInspect:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


@dataclass(frozen=True)
class ArmatureCreate:
    name: str
    transform: Transform
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"name", "transform", "expected_scene_revision"})
        return cls(
            object_name(data["name"]),
            Transform.parse(data["transform"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


@dataclass(frozen=True)
class BoneCreate:
    target: ObjectTarget
    expected_rig_revision: str
    name: str
    head: tuple[float, float, float]
    tail: tuple[float, float, float]
    use_deform: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"target", "expected_rig_revision", "name", "head", "tail"},
            {"use_deform"},
        )
        head = vector3(data["head"], "head", MAX_BONE_COORDINATE)
        tail = vector3(data["tail"], "tail", MAX_BONE_COORDINATE)
        if head == tail:
            raise invalid("Bone head and tail must differ")
        use_deform = data.get("use_deform", True)
        if type(use_deform) is not bool:
            raise invalid("use_deform must be a boolean")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_rig_revision"], "expected_rig_revision", limit=64),
            object_name(data["name"]),
            head,
            tail,
            use_deform,
        )


@dataclass(frozen=True)
class BoneHierarchyEdit:
    target: ObjectTarget
    expected_rig_revision: str
    bone_name: str
    new_name: str
    parent_name: str | None
    use_connect: bool

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_rig_revision",
                "bone_name",
                "new_name",
                "parent_name",
                "use_connect",
            },
        )
        parent_name = data["parent_name"]
        if parent_name is not None:
            parent_name = object_name(parent_name)
        use_connect = data["use_connect"]
        if type(use_connect) is not bool:
            raise invalid("use_connect must be a boolean")
        if use_connect and parent_name is None:
            raise invalid("Connected bones require a parent")
        bone_name = object_name(data["bone_name"])
        if parent_name == bone_name:
            raise invalid("Bone cannot parent itself")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_rig_revision"], "expected_rig_revision", limit=64),
            bone_name,
            object_name(data["new_name"]),
            parent_name,
            use_connect,
        )


@dataclass(frozen=True)
class BoneSymmetryEdit:
    target: ObjectTarget
    expected_rig_revision: str
    left_name: str
    right_name: str
    left_head: tuple[float, float, float]
    left_tail: tuple[float, float, float]

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_rig_revision",
                "left_name",
                "right_name",
                "left_head",
                "left_tail",
            },
        )
        left_name = object_name(data["left_name"])
        right_name = object_name(data["right_name"])
        if not left_name.endswith(".L") or right_name != left_name[:-2] + ".R":
            raise invalid("Symmetry pair must use matching .L/.R names")
        left_head = vector3(data["left_head"], "left_head", MAX_BONE_COORDINATE)
        left_tail = vector3(data["left_tail"], "left_tail", MAX_BONE_COORDINATE)
        if left_head == left_tail:
            raise invalid("Bone head and tail must differ")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_rig_revision"], "expected_rig_revision", limit=64),
            left_name,
            right_name,
            left_head,
            left_tail,
        )


def _finite(value, label):
    value = float(value)
    if not isfinite(value):
        raise AgentError(ErrorCode.SAFETY_DENIED, f"{label} contains non-finite values")
    return value


def _vector(value, label, size):
    values = list(value)
    if len(values) != size:
        raise AgentError(ErrorCode.SAFETY_DENIED, f"{label} has unexpected dimensions")
    return [_finite(item, label) for item in values]


def _matrix(value, label):
    rows = [list(row) for row in value]
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise AgentError(ErrorCode.SAFETY_DENIED, f"{label} has unexpected dimensions")
    return [[_finite(item, label) for item in row] for row in rows]


class RiggingOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    @staticmethod
    def _constraint_snapshot(constraint):
        name = bounded_text(getattr(constraint, "name", ""), limit=256)
        kind = bounded_text(getattr(constraint, "type", "UNKNOWN"), limit=64)
        influence = getattr(constraint, "influence", 1.0)
        return {
            "name": name,
            "type": kind,
            "mute": bool(getattr(constraint, "mute", False)),
            "influence": _finite(influence, "pose constraint influence"),
        }

    def _bone_snapshot(self, bone):
        name = bounded_text(bone.name, limit=256)
        parent = getattr(bone, "parent", None)
        parent_name = bounded_text(parent.name, limit=256) if parent is not None else None
        matrix_local = getattr(bone, "matrix_local", None)
        return {
            "name": name,
            "parent": parent_name,
            "head_local": _vector(bone.head_local, "bone head", 3),
            "tail_local": _vector(bone.tail_local, "bone tail", 3),
            "matrix_local": (
                _matrix(matrix_local, "bone matrix") if matrix_local is not None else None
            ),
            "use_connect": bool(getattr(bone, "use_connect", False)),
            "use_deform": bool(getattr(bone, "use_deform", True)),
            "inherit_scale": bounded_text(
                getattr(bone, "inherit_scale", "FULL"),
                limit=64,
            ),
        }

    def _pose_snapshot(self, pose_bone):
        name = bounded_text(pose_bone.name, limit=256)
        constraints = list(getattr(pose_bone, "constraints", ()))
        if len(constraints) > MAX_POSE_CONSTRAINTS_PER_BONE:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Pose bone constraint count exceeds inspection bound",
            )
        rotation_mode = bounded_text(getattr(pose_bone, "rotation_mode", "QUATERNION"), limit=64)
        return {
            "name": name,
            "rotation_mode": rotation_mode,
            "location": _vector(getattr(pose_bone, "location", (0, 0, 0)), "pose location", 3),
            "rotation_euler": _vector(
                getattr(pose_bone, "rotation_euler", (0, 0, 0)),
                "pose Euler rotation",
                3,
            ),
            "rotation_quaternion": _vector(
                getattr(pose_bone, "rotation_quaternion", (1, 0, 0, 0)),
                "pose quaternion",
                4,
            ),
            "scale": _vector(getattr(pose_bone, "scale", (1, 1, 1)), "pose scale", 3),
            "constraint_count": len(constraints),
            "constraints": [self._constraint_snapshot(item) for item in constraints],
        }

    @staticmethod
    def _hierarchy_cycle(parent_by_name):
        for start in parent_by_name:
            seen = set()
            current = start
            while current is not None:
                if current in seen:
                    return True
                seen.add(current)
                current = parent_by_name.get(current)
        return False

    def _snapshot(self, obj):
        if obj.type != "ARMATURE" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Armature object required")

        bones = list(getattr(obj.data, "bones", ()))
        if len(bones) > MAX_RIG_BONES:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Armature bone count exceeds inspection bound",
            )

        pose = getattr(obj, "pose", None)
        pose_bones = list(getattr(pose, "bones", ())) if pose is not None else []
        if len(pose_bones) > MAX_RIG_BONES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pose bone count exceeds inspection bound")

        total_constraints = sum(len(getattr(item, "constraints", ())) for item in pose_bones)
        if total_constraints > MAX_POSE_CONSTRAINTS:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Total pose constraint count exceeds inspection bound",
            )

        bone_data = [self._bone_snapshot(item) for item in bones]
        pose_data = [self._pose_snapshot(item) for item in pose_bones]
        bone_data.sort(key=lambda item: item["name"])
        pose_data.sort(key=lambda item: item["name"])

        parent_by_name = {item["name"]: item["parent"] for item in bone_data}
        roots = sorted(name for name, parent in parent_by_name.items() if parent is None)
        bone_names = {item["name"] for item in bone_data}
        pose_names = {item["name"] for item in pose_data}

        data = {
            "object_id": self.inspector.identity(obj),
            "name": bounded_text(obj.name, limit=256),
            "armature_name": bounded_text(obj.data.name, limit=256),
            "object_revision": self.inspector.snapshot(obj)["revision"],
            "linked_object": obj.library is not None,
            "linked_armature_data": getattr(obj.data, "library", None) is not None,
            "bone_count": len(bone_data),
            "pose_bone_count": len(pose_data),
            "root_bones": roots,
            "root_count": len(roots),
            "hierarchy_cycle": self._hierarchy_cycle(parent_by_name),
            "bones": bone_data,
            "pose_bones": pose_data,
            "pose_missing_bones": sorted(bone_names - pose_names),
            "pose_extra_bones": sorted(pose_names - bone_names),
            "total_pose_constraint_count": total_constraints,
            "source_only": True,
            "real_runtime_verified": False,
        }
        data["rig_revision"] = revision(
            {
                "armature_name": data["armature_name"],
                "bones": bone_data,
                "pose_bones": pose_data,
                "linked_object": data["linked_object"],
                "linked_armature_data": data["linked_armature_data"],
            }
        )
        return data

    def inspect(self, request: Request, action: ArmatureInspect):
        data = self._snapshot(self.inspector.resolve(action.object_id))
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def _remove_created_armature(self, obj, armature):
        if obj is not None:
            self.bpy.data.objects.remove(obj, do_unlink=True)
        if armature is not None and armature.users == 0:
            self.bpy.data.armatures.remove(armature)

    def create_armature(self, request: Request, action: ArmatureCreate):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        self.objects._free_name(action.name)
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object mode required")
        data_name = action.name + "Armature"
        if self.bpy.data.armatures.get(data_name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Armature data name already exists")

        armature = None
        obj = None
        try:
            armature = self.bpy.data.armatures.new(data_name)
            obj = self.bpy.data.objects.new(action.name, armature)
            self.bpy.context.scene.collection.objects.link(obj)
            self.objects._transform(obj, action.transform)
            self.bpy.context.view_layer.update()

            rig = self._snapshot(obj)
            object_data = self.objects._readback(obj)
            actual = {
                "object": object_data,
                "rig": rig,
            }
            expected = {
                "object": {
                    "name": action.name,
                    "type": "ARMATURE",
                    "scene_member": True,
                    "transform": action.transform.to_dict() | {"rotation_mode": "XYZ"},
                },
                "rig": {
                    "name": action.name,
                    "armature_name": data_name,
                    "bone_count": 0,
                    "pose_bone_count": 0,
                    "linked_object": False,
                    "linked_armature_data": False,
                },
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": None, "after": actual},
                    verification=verification.to_dict(),
                )
            self._remove_created_armature(obj, armature)
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {"before": None, "after": actual, "rolled_back": True},
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Armature creation readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            self._remove_created_armature(obj, armature)
            raise

    def _set_mode(self, mode):
        outcome = self.bpy.ops.object.mode_set(mode=mode)
        if outcome != {"FINISHED"}:
            raise AgentError(ErrorCode.EXECUTION_ERROR, "Blender mode transition did not finish")
        self.bpy.context.view_layer.update()

    def _remove_bone(self, obj, name):
        current = self.bpy.context.mode
        if current != "EDIT_ARMATURE":
            self._set_mode("EDIT")
        bone = obj.data.edit_bones.get(name)
        if bone is not None:
            obj.data.edit_bones.remove(bone)
        self._set_mode("OBJECT")

    def create_bone(self, request: Request, action: BoneCreate):
        obj, target_before = self.inspector.target(action.target)
        if obj.type != "ARMATURE" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Armature object required")
        if (
            obj.library is not None
            or obj.override_library is not None
            or not obj.is_editable
            or getattr(obj.data, "library", None) is not None
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Editable local armature required")
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object mode required")
        if (
            getattr(self.bpy.context.view_layer.objects, "active", None) != obj
            or not obj.select_get()
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Bone creation requires the target armature selected and active",
            )

        before = self._snapshot(obj)
        require_revision(action.expected_rig_revision, before["rig_revision"])
        if before["bone_count"] >= MAX_RIG_BONES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Armature bone limit reached")
        if any(item["name"] == action.name for item in before["bones"]):
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Bone name already exists")

        created = False
        try:
            self._set_mode("EDIT")
            bone = obj.data.edit_bones.new(action.name)
            created = True
            bone.head = action.head
            bone.tail = action.tail
            bone.use_connect = False
            bone.use_deform = action.use_deform
            self._set_mode("OBJECT")

            after = self._snapshot(obj)
            created_bone = next(
                (item for item in after["bones"] if item["name"] == action.name),
                None,
            )
            actual = {
                "bone_count": after["bone_count"],
                "created_bone": created_bone,
                "mode": self.bpy.context.mode,
                "object_id": after["object_id"],
            }
            expected = {
                "bone_count": before["bone_count"] + 1,
                "created_bone": {
                    "name": action.name,
                    "parent": None,
                    "head_local": list(action.head),
                    "tail_local": list(action.tail),
                    "use_connect": False,
                    "use_deform": action.use_deform,
                },
                "mode": "OBJECT",
                "object_id": target_before["object_id"],
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": before, "after": after},
                    verification=verification.to_dict(),
                )

            self._remove_bone(obj, action.name)
            recovered = self._snapshot(obj)
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": after,
                    "rolled_back": True,
                    "recovery_verified": recovered["rig_revision"] == before["rig_revision"],
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Bone creation readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if created:
                try:
                    self._remove_bone(obj, action.name)
                except Exception:
                    pass
            elif self.bpy.context.mode == "EDIT_ARMATURE":
                try:
                    self._set_mode("OBJECT")
                except Exception:
                    pass
            raise


    def _require_editable_active_armature(self, target):
        obj, target_before = self.inspector.target(target)
        if obj.type != "ARMATURE" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Armature object required")
        if (
            obj.library is not None
            or obj.override_library is not None
            or not obj.is_editable
            or getattr(obj.data, "library", None) is not None
        ):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Editable local armature required")
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object mode required")
        if (
            getattr(self.bpy.context.view_layer.objects, "active", None) != obj
            or not obj.select_get()
        ):
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Rig editing requires the target armature selected and active",
            )
        return obj, target_before

    @staticmethod
    def _bone_from_snapshot(snapshot, name):
        return next((item for item in snapshot["bones"] if item["name"] == name), None)

    def _restore_edit_bone(self, obj, current_name, state):
        if self.bpy.context.mode != "EDIT_ARMATURE":
            self._set_mode("EDIT")
        bone = obj.data.edit_bones.get(current_name) or obj.data.edit_bones.get(state["name"])
        if bone is None:
            raise AgentError(ErrorCode.EXECUTION_ERROR, "Edited bone disappeared during recovery")
        bone.use_connect = False
        bone.name = state["name"]
        bone.parent = (
            obj.data.edit_bones.get(state["parent"]) if state["parent"] is not None else None
        )
        bone.head = state["head_local"]
        bone.tail = state["tail_local"]
        bone.use_connect = state["use_connect"]

    def edit_bone_hierarchy(self, request: Request, action: BoneHierarchyEdit):
        obj, target_before = self._require_editable_active_armature(action.target)
        before = self._snapshot(obj)
        require_revision(action.expected_rig_revision, before["rig_revision"])
        original = self._bone_from_snapshot(before, action.bone_name)
        if original is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Bone not found")
        if (
            action.parent_name is not None
            and self._bone_from_snapshot(before, action.parent_name) is None
        ):
            raise AgentError(ErrorCode.NOT_FOUND, "Parent bone not found")
        if (
            action.new_name != action.bone_name
            and self._bone_from_snapshot(before, action.new_name)
        ):
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Bone name already exists")

        parent_by_name = {item["name"]: item["parent"] for item in before["bones"]}
        parent_by_name[action.bone_name] = action.parent_name
        if self._hierarchy_cycle(parent_by_name):
            raise AgentError(ErrorCode.SAFETY_DENIED, "Bone parenting would create a cycle")

        final_name = action.new_name
        changed = False
        try:
            self._set_mode("EDIT")
            bone = obj.data.edit_bones.get(action.bone_name)
            parent = (
                obj.data.edit_bones.get(action.parent_name)
                if action.parent_name is not None
                else None
            )
            if bone is None:
                raise AgentError(ErrorCode.NOT_FOUND, "Bone not found in edit armature")
            if action.parent_name is not None and parent is None:
                raise AgentError(ErrorCode.NOT_FOUND, "Parent bone not found in edit armature")
            bone.use_connect = False
            bone.parent = parent
            if action.use_connect:
                bone.head = list(parent.tail)
            bone.use_connect = action.use_connect
            bone.name = final_name
            changed = True
            self._set_mode("OBJECT")

            after = self._snapshot(obj)
            edited = self._bone_from_snapshot(after, final_name)
            expected_head = (
                list(self._bone_from_snapshot(before, action.parent_name)["tail_local"])
                if action.use_connect
                else original["head_local"]
            )
            actual = {
                "bone_count": after["bone_count"],
                "edited_bone": edited,
                "mode": self.bpy.context.mode,
                "object_id": after["object_id"],
                "hierarchy_cycle": after["hierarchy_cycle"],
            }
            expected = {
                "bone_count": before["bone_count"],
                "edited_bone": {
                    "name": final_name,
                    "parent": action.parent_name,
                    "head_local": expected_head,
                    "tail_local": original["tail_local"],
                    "use_connect": action.use_connect,
                    "use_deform": original["use_deform"],
                },
                "mode": "OBJECT",
                "object_id": target_before["object_id"],
                "hierarchy_cycle": False,
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": before, "after": after},
                    verification=verification.to_dict(),
                )

            self._restore_edit_bone(obj, final_name, original)
            self._set_mode("OBJECT")
            recovered = self._snapshot(obj)
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": after,
                    "rolled_back": True,
                    "recovery_verified": recovered["rig_revision"] == before["rig_revision"],
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Bone hierarchy readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if changed:
                try:
                    self._restore_edit_bone(obj, final_name, original)
                    self._set_mode("OBJECT")
                except Exception:
                    pass
            elif self.bpy.context.mode == "EDIT_ARMATURE":
                try:
                    self._set_mode("OBJECT")
                except Exception:
                    pass
            raise

    def edit_bone_symmetry(self, request: Request, action: BoneSymmetryEdit):
        obj, target_before = self._require_editable_active_armature(action.target)
        before = self._snapshot(obj)
        require_revision(action.expected_rig_revision, before["rig_revision"])
        left_before = self._bone_from_snapshot(before, action.left_name)
        right_before = self._bone_from_snapshot(before, action.right_name)
        if left_before is None or right_before is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Symmetry pair bone not found")
        if left_before["use_connect"] or right_before["use_connect"]:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Symmetry coordinate editing requires disconnected bones",
            )

        right_head = [-action.left_head[0], action.left_head[1], action.left_head[2]]
        right_tail = [-action.left_tail[0], action.left_tail[1], action.left_tail[2]]
        changed = False
        try:
            self._set_mode("EDIT")
            left = obj.data.edit_bones.get(action.left_name)
            right = obj.data.edit_bones.get(action.right_name)
            if left is None or right is None:
                raise AgentError(ErrorCode.NOT_FOUND, "Symmetry pair missing in edit armature")
            left.head = action.left_head
            left.tail = action.left_tail
            right.head = right_head
            right.tail = right_tail
            changed = True
            self._set_mode("OBJECT")

            after = self._snapshot(obj)
            actual = {
                "bone_count": after["bone_count"],
                "left": self._bone_from_snapshot(after, action.left_name),
                "right": self._bone_from_snapshot(after, action.right_name),
                "mode": self.bpy.context.mode,
                "object_id": after["object_id"],
            }
            expected = {
                "bone_count": before["bone_count"],
                "left": {
                    "name": action.left_name,
                    "head_local": list(action.left_head),
                    "tail_local": list(action.left_tail),
                    "parent": left_before["parent"],
                    "use_connect": False,
                    "use_deform": left_before["use_deform"],
                },
                "right": {
                    "name": action.right_name,
                    "head_local": right_head,
                    "tail_local": right_tail,
                    "parent": right_before["parent"],
                    "use_connect": False,
                    "use_deform": right_before["use_deform"],
                },
                "mode": "OBJECT",
                "object_id": target_before["object_id"],
            }
            verification = compare(expected, actual)
            if verification.matched:
                return Result(
                    request.request_id,
                    request.command_id,
                    Status.VERIFIED,
                    {"before": before, "after": after},
                    verification=verification.to_dict(),
                )

            self._set_mode("EDIT")
            left = obj.data.edit_bones.get(action.left_name)
            right = obj.data.edit_bones.get(action.right_name)
            left.head, left.tail = left_before["head_local"], left_before["tail_local"]
            right.head, right.tail = right_before["head_local"], right_before["tail_local"]
            self._set_mode("OBJECT")
            recovered = self._snapshot(obj)
            return Result(
                request.request_id,
                request.command_id,
                Status.FAILED,
                {
                    "before": before,
                    "after": after,
                    "rolled_back": True,
                    "recovery_verified": recovered["rig_revision"] == before["rig_revision"],
                },
                AgentError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Bone symmetry readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if changed:
                try:
                    if self.bpy.context.mode != "EDIT_ARMATURE":
                        self._set_mode("EDIT")
                    left = obj.data.edit_bones.get(action.left_name)
                    right = obj.data.edit_bones.get(action.right_name)
                    if left is not None:
                        left.head, left.tail = (
                            left_before["head_local"],
                            left_before["tail_local"],
                        )
                    if right is not None:
                        right.head, right.tail = (
                            right_before["head_local"],
                            right_before["tail_local"],
                        )
                    self._set_mode("OBJECT")
                except Exception:
                    pass
            elif self.bpy.context.mode == "EDIT_ARMATURE":
                try:
                    self._set_mode("OBJECT")
                except Exception:
                    pass
            raise

    def tools(self):
        return [
            Tool(
                "rig.armature_inspect",
                SafetyClass.READ_ONLY,
                ArmatureInspect.parse,
                self.inspect,
            ),
            Tool(
                "rig.armature_create",
                SafetyClass.MUTATION,
                ArmatureCreate.parse,
                self.create_armature,
            ),
            Tool(
                "rig.bone_create",
                SafetyClass.MUTATION,
                BoneCreate.parse,
                self.create_bone,
            ),
            Tool(
                "rig.bone_hierarchy_edit",
                SafetyClass.MUTATION,
                BoneHierarchyEdit.parse,
                self.edit_bone_hierarchy,
            ),
            Tool(
                "rig.bone_symmetry_edit",
                SafetyClass.MUTATION,
                BoneSymmetryEdit.parse,
                self.edit_bone_symmetry,
            ),
        ]
