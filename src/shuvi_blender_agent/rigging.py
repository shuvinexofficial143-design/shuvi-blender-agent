"""Level 6 rigging: bounded inspection, hierarchy editing and pose controls."""

from dataclasses import dataclass
from math import isfinite, sqrt

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import bounded_text, revision
from .models import ObjectTarget, Transform, object_name, vector3
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, number, string
from .verification import compare

MAX_RIG_BONES = 256
MAX_POSE_CONSTRAINTS_PER_BONE = 64
MAX_POSE_CONSTRAINTS = 512
MAX_BONE_COORDINATE = 100_000
MAX_POSE_LOCATION = 100_000
MAX_POSE_ROTATION = 1_000
MAX_POSE_SCALE = 1_000


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


@dataclass(frozen=True)
class PoseBoneTransform:
    target: ObjectTarget
    expected_rig_revision: str
    bone_name: str
    location: tuple[float, float, float]
    rotation_mode: str
    rotation: tuple[float, ...]
    scale: tuple[float, float, float]

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_rig_revision",
                "bone_name",
                "location",
                "rotation_mode",
                "rotation",
                "scale",
            },
        )
        rotation_mode = data["rotation_mode"]
        if not isinstance(rotation_mode, str) or rotation_mode not in {"XYZ", "QUATERNION"}:
            raise invalid("rotation_mode must be XYZ or QUATERNION")
        location = vector3(data["location"], "location", MAX_POSE_LOCATION)
        scale_raw = data["scale"]
        if not isinstance(scale_raw, (list, tuple)) or len(scale_raw) != 3:
            raise invalid("scale must have exactly three components")
        scale = tuple(number(item, "scale", 0.001, MAX_POSE_SCALE) for item in scale_raw)
        rotation_raw = data["rotation"]
        if rotation_mode == "XYZ":
            rotation = vector3(rotation_raw, "rotation", MAX_POSE_ROTATION)
        else:
            if not isinstance(rotation_raw, (list, tuple)) or len(rotation_raw) != 4:
                raise invalid("Quaternion rotation must have exactly four components")
            quaternion = tuple(number(item, "rotation", -1.0, 1.0) for item in rotation_raw)
            magnitude = sqrt(sum(item * item for item in quaternion))
            if magnitude < 1e-8:
                raise invalid("Quaternion rotation must be non-zero")
            rotation = tuple(item / magnitude for item in quaternion)
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_rig_revision"], "expected_rig_revision", limit=64),
            object_name(data["bone_name"]),
            location,
            rotation_mode,
            rotation,
            scale,
        )


@dataclass(frozen=True)
class PoseBoneReset:
    target: ObjectTarget
    expected_rig_revision: str
    bone_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_rig_revision", "bone_name"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_rig_revision"], "expected_rig_revision", limit=64),
            object_name(data["bone_name"]),
        )


@dataclass(frozen=True)
class PoseConstraintCreate:
    target: ObjectTarget
    expected_rig_revision: str
    bone_name: str
    constraint_name: str
    constraint_type: str
    influence: float
    mute: bool
    target_bone_name: str | None = None
    chain_count: int | None = None
    use_limit_x: bool | None = None
    min_x: float | None = None
    max_x: float | None = None
    use_limit_y: bool | None = None
    min_y: float | None = None
    max_y: float | None = None
    use_limit_z: bool | None = None
    min_z: float | None = None
    max_z: float | None = None

    @classmethod
    def parse(cls, data):
        common = {
            "target",
            "expected_rig_revision",
            "bone_name",
            "constraint_name",
            "constraint_type",
            "influence",
            "mute",
        }
        limit_fields = {
            "use_limit_x",
            "min_x",
            "max_x",
            "use_limit_y",
            "min_y",
            "max_y",
            "use_limit_z",
            "min_z",
            "max_z",
        }
        ik_fields = {"target_bone_name", "chain_count"}
        fields(data, common, limit_fields | ik_fields)
        kind = data["constraint_type"]
        if not isinstance(kind, str) or kind not in {"LIMIT_ROTATION", "IK"}:
            raise invalid("constraint_type must be LIMIT_ROTATION or IK")
        if type(data["mute"]) is not bool:
            raise invalid("mute must be a boolean")
        extras = set(data) - common
        if kind == "LIMIT_ROTATION":
            if extras != limit_fields:
                raise invalid("LIMIT_ROTATION requires exactly the bounded limit fields")
            flags = []
            limits = []
            for axis in ("x", "y", "z"):
                flag = data[f"use_limit_{axis}"]
                if type(flag) is not bool:
                    raise invalid(f"use_limit_{axis} must be a boolean")
                low = number(data[f"min_{axis}"], f"min_{axis}", -MAX_POSE_ROTATION, MAX_POSE_ROTATION)
                high = number(data[f"max_{axis}"], f"max_{axis}", -MAX_POSE_ROTATION, MAX_POSE_ROTATION)
                if low > high:
                    raise invalid(f"min_{axis} must not exceed max_{axis}")
                flags.append(flag)
                limits.extend((low, high))
            return cls(
                ObjectTarget.parse(data["target"]),
                string(data["expected_rig_revision"], "expected_rig_revision", limit=64),
                object_name(data["bone_name"]),
                object_name(data["constraint_name"]),
                kind,
                number(data["influence"], "influence", 0.0, 1.0),
                data["mute"],
                use_limit_x=flags[0],
                min_x=limits[0],
                max_x=limits[1],
                use_limit_y=flags[1],
                min_y=limits[2],
                max_y=limits[3],
                use_limit_z=flags[2],
                min_z=limits[4],
                max_z=limits[5],
            )
        if extras != ik_fields:
            raise invalid("IK requires exactly target_bone_name and chain_count")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_rig_revision"], "expected_rig_revision", limit=64),
            object_name(data["bone_name"]),
            object_name(data["constraint_name"]),
            kind,
            number(data["influence"], "influence", 0.0, 1.0),
            data["mute"],
            target_bone_name=object_name(data["target_bone_name"]),
            chain_count=integer(data["chain_count"], "chain_count", 1, 64),
        )


@dataclass(frozen=True)
class PoseConstraintRemove:
    target: ObjectTarget
    expected_rig_revision: str
    bone_name: str
    constraint_name: str
    expected_constraint_type: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_rig_revision",
                "bone_name",
                "constraint_name",
                "expected_constraint_type",
            },
        )
        kind = data["expected_constraint_type"]
        if not isinstance(kind, str) or kind not in {"LIMIT_ROTATION", "IK"}:
            raise invalid("expected_constraint_type must be LIMIT_ROTATION or IK")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_rig_revision"], "expected_rig_revision", limit=64),
            object_name(data["bone_name"]),
            object_name(data["constraint_name"]),
            kind,
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
        data = {
            "name": name,
            "type": kind,
            "mute": bool(getattr(constraint, "mute", False)),
            "influence": _finite(influence, "pose constraint influence"),
        }
        if kind == "LIMIT_ROTATION":
            for axis in ("x", "y", "z"):
                data[f"use_limit_{axis}"] = bool(getattr(constraint, f"use_limit_{axis}", False))
                data[f"min_{axis}"] = _finite(
                    getattr(constraint, f"min_{axis}", 0.0),
                    f"pose constraint min_{axis}",
                )
                data[f"max_{axis}"] = _finite(
                    getattr(constraint, f"max_{axis}", 0.0),
                    f"pose constraint max_{axis}",
                )
        elif kind == "IK":
            target = getattr(constraint, "target", None)
            target_name = getattr(target, "name", None) if target is not None else None
            if target_name is not None:
                target_name = bounded_text(target_name, limit=256)
            subtarget = bounded_text(getattr(constraint, "subtarget", ""), limit=256)
            chain_count = getattr(constraint, "chain_count", 0)
            if type(chain_count) is not int or not 0 <= chain_count <= MAX_RIG_BONES:
                raise AgentError(ErrorCode.SAFETY_DENIED, "IK chain count exceeds inspection bound")
            data.update(
                {
                    "target_object_name": target_name,
                    "target_bone_name": subtarget,
                    "chain_count": chain_count,
                }
            )
        return data

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
        if action.new_name != action.bone_name and self._bone_from_snapshot(
            before, action.new_name
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

    @staticmethod
    def _pose_bone_object(obj, name):
        pose = getattr(obj, "pose", None)
        bones = list(getattr(pose, "bones", ())) if pose is not None else []
        return next((item for item in bones if getattr(item, "name", None) == name), None)

    @staticmethod
    def _restore_pose_state(pose_bone, state):
        pose_bone.rotation_mode = state["rotation_mode"]
        pose_bone.location = list(state["location"])
        pose_bone.rotation_euler = list(state["rotation_euler"])
        pose_bone.rotation_quaternion = list(state["rotation_quaternion"])
        pose_bone.scale = list(state["scale"])

    def _pose_target(self, action):
        obj, target_before = self._require_editable_active_armature(action.target)
        before = self._snapshot(obj)
        require_revision(action.expected_rig_revision, before["rig_revision"])
        pose_state = next(
            (item for item in before["pose_bones"] if item["name"] == action.bone_name),
            None,
        )
        if pose_state is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose bone not found")
        pose_bone = self._pose_bone_object(obj, action.bone_name)
        if pose_bone is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Pose bone unavailable")
        return obj, target_before, before, pose_bone, pose_state

    def set_pose_bone_transform(self, request: Request, action: PoseBoneTransform):
        obj, target_before, before, pose_bone, pose_before = self._pose_target(action)
        changed = False
        try:
            pose_bone.location = list(action.location)
            pose_bone.scale = list(action.scale)
            pose_bone.rotation_mode = action.rotation_mode
            if action.rotation_mode == "XYZ":
                pose_bone.rotation_euler = list(action.rotation)
            else:
                pose_bone.rotation_quaternion = list(action.rotation)
            changed = True
            self.bpy.context.view_layer.update()

            after = self._snapshot(obj)
            pose_after = next(
                (item for item in after["pose_bones"] if item["name"] == action.bone_name),
                None,
            )
            expected_pose = {
                "name": action.bone_name,
                "rotation_mode": action.rotation_mode,
                "location": list(action.location),
                "scale": list(action.scale),
            }
            if action.rotation_mode == "XYZ":
                expected_pose["rotation_euler"] = list(action.rotation)
            else:
                expected_pose["rotation_quaternion"] = list(action.rotation)
            actual = {
                "pose_bone": pose_after,
                "object_id": after["object_id"],
                "mode": self.bpy.context.mode,
            }
            expected = {
                "pose_bone": expected_pose,
                "object_id": target_before["object_id"],
                "mode": "OBJECT",
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

            self._restore_pose_state(pose_bone, pose_before)
            self.bpy.context.view_layer.update()
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
                    "Pose transform readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if changed:
                try:
                    self._restore_pose_state(pose_bone, pose_before)
                    self.bpy.context.view_layer.update()
                except Exception:
                    pass
            raise

    def reset_pose_bone(self, request: Request, action: PoseBoneReset):
        obj, target_before, before, pose_bone, pose_before = self._pose_target(action)
        changed = False
        try:
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.location = [0.0, 0.0, 0.0]
            pose_bone.rotation_euler = [0.0, 0.0, 0.0]
            pose_bone.rotation_quaternion = [1.0, 0.0, 0.0, 0.0]
            pose_bone.scale = [1.0, 1.0, 1.0]
            changed = True
            self.bpy.context.view_layer.update()

            after = self._snapshot(obj)
            pose_after = next(
                (item for item in after["pose_bones"] if item["name"] == action.bone_name),
                None,
            )
            actual = {
                "pose_bone": pose_after,
                "object_id": after["object_id"],
                "mode": self.bpy.context.mode,
            }
            expected = {
                "pose_bone": {
                    "name": action.bone_name,
                    "rotation_mode": "QUATERNION",
                    "location": [0.0, 0.0, 0.0],
                    "rotation_euler": [0.0, 0.0, 0.0],
                    "rotation_quaternion": [1.0, 0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                },
                "object_id": target_before["object_id"],
                "mode": "OBJECT",
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

            self._restore_pose_state(pose_bone, pose_before)
            self.bpy.context.view_layer.update()
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
                    "Pose reset readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if changed:
                try:
                    self._restore_pose_state(pose_bone, pose_before)
                    self.bpy.context.view_layer.update()
                except Exception:
                    pass
            raise


    @staticmethod
    def _constraint_object(pose_bone, name):
        return next(
            (item for item in getattr(pose_bone, "constraints", ()) if getattr(item, "name", None) == name),
            None,
        )

    @staticmethod
    def _constraint_from_snapshot(pose_state, name):
        return next((item for item in pose_state["constraints"] if item["name"] == name), None)

    @staticmethod
    def _apply_constraint_state(constraint, state, obj):
        constraint.name = state["name"]
        constraint.influence = state["influence"]
        constraint.mute = state["mute"]
        if state["type"] == "LIMIT_ROTATION":
            for axis in ("x", "y", "z"):
                setattr(constraint, f"use_limit_{axis}", state[f"use_limit_{axis}"])
                setattr(constraint, f"min_{axis}", state[f"min_{axis}"])
                setattr(constraint, f"max_{axis}", state[f"max_{axis}"])
        elif state["type"] == "IK":
            constraint.target = obj
            constraint.subtarget = state["target_bone_name"]
            constraint.chain_count = state["chain_count"]

    @staticmethod
    def _validate_removable_constraint(state, obj):
        if not 0.0 <= state["influence"] <= 1.0:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Constraint influence is outside managed bounds")
        if state["type"] == "LIMIT_ROTATION":
            for axis in ("x", "y", "z"):
                low = state[f"min_{axis}"]
                high = state[f"max_{axis}"]
                if (
                    low < -MAX_POSE_ROTATION
                    or high > MAX_POSE_ROTATION
                    or low > high
                ):
                    raise AgentError(
                        ErrorCode.SAFETY_DENIED,
                        "Limit Rotation settings are outside managed bounds",
                    )
        elif state["type"] == "IK":
            if (
                state["target_object_name"] != obj.name
                or not state["target_bone_name"]
                or not 1 <= state["chain_count"] <= 64
            ):
                raise AgentError(
                    ErrorCode.SAFETY_DENIED,
                    "IK constraint is outside managed same-armature bounds",
                )

    def create_pose_constraint(self, request: Request, action: PoseConstraintCreate):
        obj, target_before, before, pose_bone, pose_before = self._pose_target(action)
        if self._constraint_from_snapshot(pose_before, action.constraint_name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Constraint name already exists")
        if pose_before["constraint_count"] >= MAX_POSE_CONSTRAINTS_PER_BONE:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Pose bone constraint limit reached")
        if before["total_pose_constraint_count"] >= MAX_POSE_CONSTRAINTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Total pose constraint limit reached")
        if action.constraint_type == "IK":
            if action.target_bone_name == action.bone_name:
                raise AgentError(ErrorCode.SAFETY_DENIED, "IK target bone must differ from owner bone")
            bone_names = {item["name"] for item in before["bones"]}
            pose_names = {item["name"] for item in before["pose_bones"]}
            if action.target_bone_name not in bone_names or action.target_bone_name not in pose_names:
                raise AgentError(ErrorCode.NOT_FOUND, "IK target bone not found in armature")

        created = None
        try:
            created = pose_bone.constraints.new(action.constraint_type)
            created.name = action.constraint_name
            state = {
                "name": action.constraint_name,
                "type": action.constraint_type,
                "mute": action.mute,
                "influence": action.influence,
            }
            if action.constraint_type == "LIMIT_ROTATION":
                for axis in ("x", "y", "z"):
                    state[f"use_limit_{axis}"] = getattr(action, f"use_limit_{axis}")
                    state[f"min_{axis}"] = getattr(action, f"min_{axis}")
                    state[f"max_{axis}"] = getattr(action, f"max_{axis}")
            else:
                state.update(
                    {
                        "target_object_name": obj.name,
                        "target_bone_name": action.target_bone_name,
                        "chain_count": action.chain_count,
                    }
                )
            self._apply_constraint_state(created, state, obj)
            self.bpy.context.view_layer.update()

            after = self._snapshot(obj)
            pose_after = next(
                item for item in after["pose_bones"] if item["name"] == action.bone_name
            )
            actual = {
                "constraint": self._constraint_from_snapshot(pose_after, action.constraint_name),
                "constraint_count": pose_after["constraint_count"],
                "total_pose_constraint_count": after["total_pose_constraint_count"],
                "object_id": after["object_id"],
                "mode": self.bpy.context.mode,
            }
            expected = {
                "constraint": state,
                "constraint_count": pose_before["constraint_count"] + 1,
                "total_pose_constraint_count": before["total_pose_constraint_count"] + 1,
                "object_id": target_before["object_id"],
                "mode": "OBJECT",
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

            current = self._constraint_object(pose_bone, action.constraint_name)
            if current is not None:
                pose_bone.constraints.remove(current)
            self.bpy.context.view_layer.update()
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
                    "Constraint creation readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if created is not None:
                try:
                    current = self._constraint_object(pose_bone, action.constraint_name)
                    if current is not None:
                        pose_bone.constraints.remove(current)
                    self.bpy.context.view_layer.update()
                except Exception:
                    pass
            raise

    def remove_pose_constraint(self, request: Request, action: PoseConstraintRemove):
        obj, target_before, before, pose_bone, pose_before = self._pose_target(action)
        state = self._constraint_from_snapshot(pose_before, action.constraint_name)
        if state is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Constraint not found")
        if state["type"] != action.expected_constraint_type:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Constraint type differs from expectation")
        self._validate_removable_constraint(state, obj)
        current = self._constraint_object(pose_bone, action.constraint_name)
        if current is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Constraint unavailable")

        removed = False
        try:
            pose_bone.constraints.remove(current)
            removed = True
            self.bpy.context.view_layer.update()
            after = self._snapshot(obj)
            pose_after = next(
                item for item in after["pose_bones"] if item["name"] == action.bone_name
            )
            actual = {
                "constraint_absent": self._constraint_from_snapshot(
                    pose_after, action.constraint_name
                )
                is None,
                "constraint_count": pose_after["constraint_count"],
                "total_pose_constraint_count": after["total_pose_constraint_count"],
                "object_id": after["object_id"],
                "mode": self.bpy.context.mode,
            }
            expected = {
                "constraint_absent": True,
                "constraint_count": pose_before["constraint_count"] - 1,
                "total_pose_constraint_count": before["total_pose_constraint_count"] - 1,
                "object_id": target_before["object_id"],
                "mode": "OBJECT",
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

            restored = pose_bone.constraints.new(state["type"])
            self._apply_constraint_state(restored, state, obj)
            self.bpy.context.view_layer.update()
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
                    "Constraint removal readback differs from requested state",
                ),
                verification.to_dict(),
            )
        except Exception:
            if removed and self._constraint_object(pose_bone, action.constraint_name) is None:
                try:
                    restored = pose_bone.constraints.new(state["type"])
                    self._apply_constraint_state(restored, state, obj)
                    self.bpy.context.view_layer.update()
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
            Tool(
                "rig.pose_bone_transform",
                SafetyClass.MUTATION,
                PoseBoneTransform.parse,
                self.set_pose_bone_transform,
            ),
            Tool(
                "rig.pose_bone_reset",
                SafetyClass.MUTATION,
                PoseBoneReset.parse,
                self.reset_pose_bone,
            ),
            Tool(
                "rig.pose_constraint_create",
                SafetyClass.MUTATION,
                PoseConstraintCreate.parse,
                self.create_pose_constraint,
            ),
            Tool(
                "rig.pose_constraint_remove",
                SafetyClass.MUTATION,
                PoseConstraintRemove.parse,
                self.remove_pose_constraint,
            ),
        ]
