"""Level 6 milestone 1: bounded read-only armature and bone hierarchy inspection."""

from dataclasses import dataclass
from math import isfinite

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import bounded_text, revision
from .operations import ObjectOperations
from .safety import SafetyClass
from .tools import Tool
from .validation import fields, string

MAX_RIG_BONES = 256
MAX_POSE_CONSTRAINTS_PER_BONE = 64
MAX_POSE_CONSTRAINTS = 512


@dataclass(frozen=True)
class ArmatureInspect:
    object_id: str

    @classmethod
    def parse(cls, data):
        fields(data, {"object_id"})
        return cls(string(data["object_id"], "object_id", limit=128))


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
            "matrix_local": _matrix(matrix_local, "bone matrix") if matrix_local is not None else None,
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

    def inspect(self, request: Request, action: ArmatureInspect):
        obj = self.inspector.resolve(action.object_id)
        if obj.type != "ARMATURE" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Armature object required")

        bones = list(getattr(obj.data, "bones", ()))
        if len(bones) > MAX_RIG_BONES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Armature bone count exceeds inspection bound")

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
        return Result(request.request_id, request.command_id, Status.SUCCEEDED, data)

    def tools(self):
        return [
            Tool(
                "rig.armature_inspect",
                SafetyClass.READ_ONLY,
                ArmatureInspect.parse,
                self.inspect,
            )
        ]
