"""Level 4 milestone 6: bounded material-slot management."""

from dataclasses import dataclass

from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .inspection import revision
from .models import ObjectTarget, object_name
from .operations import ObjectOperations
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, integer, invalid, string
from .verification import compare

MAX_MATERIAL_SLOTS = 64
MAX_MATERIAL_FACES = 256


def _material_name(value):
    return object_name(value)


@dataclass(frozen=True)
class MaterialSlotLink:
    target: ObjectTarget
    expected_material_revision: str
    material_name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_material_revision", "material_name"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_material_revision"], "expected_material_revision", limit=64),
            _material_name(data["material_name"]),
        )


@dataclass(frozen=True)
class MaterialSlotReassign:
    target: ObjectTarget
    expected_material_revision: str
    slot_index: int
    material_name: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"target", "expected_material_revision", "slot_index", "material_name"},
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_material_revision"], "expected_material_revision", limit=64),
            integer(data["slot_index"], "slot_index", 0, MAX_MATERIAL_SLOTS - 1),
            _material_name(data["material_name"]),
        )


@dataclass(frozen=True)
class MaterialSlotDuplicate:
    target: ObjectTarget
    expected_material_revision: str
    source_slot_index: int
    new_material_name: str

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {
                "target",
                "expected_material_revision",
                "source_slot_index",
                "new_material_name",
            },
        )
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_material_revision"], "expected_material_revision", limit=64),
            integer(
                data["source_slot_index"],
                "source_slot_index",
                0,
                MAX_MATERIAL_SLOTS - 1,
            ),
            _material_name(data["new_material_name"]),
        )


@dataclass(frozen=True)
class MaterialSlotRemove:
    target: ObjectTarget
    expected_material_revision: str
    slot_index: int

    @classmethod
    def parse(cls, data):
        fields(data, {"target", "expected_material_revision", "slot_index"})
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_material_revision"], "expected_material_revision", limit=64),
            integer(data["slot_index"], "slot_index", 0, MAX_MATERIAL_SLOTS - 1),
        )


@dataclass(frozen=True)
class MaterialFaceAssign:
    target: ObjectTarget
    expected_material_revision: str
    slot_index: int
    face_indices: tuple[int, ...]

    @classmethod
    def parse(cls, data):
        fields(
            data,
            {"target", "expected_material_revision", "slot_index", "face_indices"},
        )
        values = data["face_indices"]
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_MATERIAL_FACES:
            raise invalid(f"face_indices requires 1..{MAX_MATERIAL_FACES} indices")
        indices = tuple(
            integer(value, "face_index", 0, MAX_MATERIAL_FACES - 1) for value in values
        )
        if len(set(indices)) != len(indices):
            raise invalid("face_indices must be unique")
        return cls(
            ObjectTarget.parse(data["target"]),
            string(data["expected_material_revision"], "expected_material_revision", limit=64),
            integer(data["slot_index"], "slot_index", 0, MAX_MATERIAL_SLOTS - 1),
            indices,
        )


class MaterialSlotOperations:
    def __init__(self, objects: ObjectOperations):
        self.objects = objects
        self.inspector, self.bpy = objects.inspector, objects.bpy

    def _snapshot(self, obj):
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        slots = list(obj.data.materials)
        faces = list(obj.data.polygons)
        if len(slots) > MAX_MATERIAL_SLOTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Material slot work limit exceeded")
        if len(faces) > MAX_MATERIAL_FACES:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Material face work limit exceeded")

        slot_names = [material.name if material is not None else None for material in slots]
        face_indices = [int(getattr(face, "material_index", 0)) for face in faces]
        if slots and any(index < 0 or index >= len(slots) for index in face_indices):
            raise AgentError(ErrorCode.VERIFICATION_FAILED, "Face material index is out of bounds")
        users = [sum(index == slot_index for index in face_indices) for slot_index in range(len(slots))]
        material_revision = revision(
            {
                "slot_names": slot_names,
                "face_material_indices": face_indices,
            }
        )
        return {
            "object_id": self.inspector.identity(obj),
            "name": obj.name,
            "slot_count": len(slots),
            "slot_names": slot_names,
            "slot_face_users": users,
            "face_count": len(faces),
            "face_material_indices": face_indices,
            "material_revision": material_revision,
        }

    def _editable(self, action):
        obj, object_before = self.inspector.target(action.target)
        self.objects._editable(obj)
        if obj.type != "MESH" or obj.data is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mesh object required")
        if obj.data.users != 1 or obj.data.library is not None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unshared local mesh data required")
        before = self._snapshot(obj)
        require_revision(action.expected_material_revision, before["material_revision"])
        return obj, object_before, before

    @staticmethod
    def _verify_view(snapshot):
        return {
            "slot_count": snapshot["slot_count"],
            "slot_names": snapshot["slot_names"],
            "face_material_indices": snapshot["face_material_indices"],
            "material_revision": snapshot["material_revision"],
        }

    def inspect(self, request: Request, object_id: str):
        obj = self.inspector.resolve(object_id)
        return Result(
            request.request_id,
            request.command_id,
            Status.SUCCEEDED,
            self._snapshot(obj),
        )

    def slot_link(self, request: Request, action: MaterialSlotLink):
        obj, object_before, before = self._editable(action)
        if before["slot_count"] >= MAX_MATERIAL_SLOTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Material slot work limit reached")
        material = self.bpy.data.materials.get(action.material_name)
        if material is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Material not found")

        obj.data.materials.append(material)
        self.bpy.context.view_layer.update()
        after = self._snapshot(obj)
        expected_names = [*before["slot_names"], action.material_name]
        expected = {
            "slot_count": before["slot_count"] + 1,
            "slot_names": expected_names,
            "face_material_indices": before["face_material_indices"],
            "material_revision": revision(
                {
                    "slot_names": expected_names,
                    "face_material_indices": before["face_material_indices"],
                }
            ),
        }
        verification = compare(expected, self._verify_view(after))
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {"before": before, "after": after, "linked_material": action.material_name},
                verification=verification.to_dict(),
            )

        obj.data.materials.pop(index=len(obj.data.materials) - 1)
        self.bpy.context.view_layer.update()
        restored = self._snapshot(obj)
        recovery = compare(self._verify_view(before), self._verify_view(restored))
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material link verification failed and recovery could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "rolled_back": True,
                "recovery_verified": True,
                "object_before": object_before,
            },
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material link readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def slot_reassign(self, request: Request, action: MaterialSlotReassign):
        obj, object_before, before = self._editable(action)
        if action.slot_index >= before["slot_count"]:
            raise invalid("Material slot index does not exist")
        material = self.bpy.data.materials.get(action.material_name)
        if material is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Material not found")
        old_material = obj.data.materials[action.slot_index]

        obj.data.materials[action.slot_index] = material
        self.bpy.context.view_layer.update()
        after = self._snapshot(obj)
        expected_names = list(before["slot_names"])
        expected_names[action.slot_index] = action.material_name
        expected = {
            "slot_count": before["slot_count"],
            "slot_names": expected_names,
            "face_material_indices": before["face_material_indices"],
            "material_revision": revision(
                {
                    "slot_names": expected_names,
                    "face_material_indices": before["face_material_indices"],
                }
            ),
        }
        verification = compare(expected, self._verify_view(after))
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "before": before,
                    "after": after,
                    "slot_index": action.slot_index,
                    "material_name": action.material_name,
                },
                verification=verification.to_dict(),
            )

        obj.data.materials[action.slot_index] = old_material
        self.bpy.context.view_layer.update()
        restored = self._snapshot(obj)
        recovery = compare(self._verify_view(before), self._verify_view(restored))
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material reassign verification failed and recovery could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "rolled_back": True,
                "recovery_verified": True,
                "object_before": object_before,
            },
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material reassign readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def slot_duplicate(self, request: Request, action: MaterialSlotDuplicate):
        obj, object_before, before = self._editable(action)
        if action.source_slot_index >= before["slot_count"]:
            raise invalid("Source material slot index does not exist")
        if before["slot_count"] >= MAX_MATERIAL_SLOTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Material slot work limit reached")
        if self.bpy.data.materials.get(action.new_material_name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Material name already exists")
        source = obj.data.materials[action.source_slot_index]
        if source is None:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Source material slot is empty")

        duplicate = source.copy()
        duplicate.name = action.new_material_name
        obj.data.materials.append(duplicate)
        self.bpy.context.view_layer.update()
        after = self._snapshot(obj)
        expected_names = [*before["slot_names"], action.new_material_name]
        expected = {
            "slot_count": before["slot_count"] + 1,
            "slot_names": expected_names,
            "face_material_indices": before["face_material_indices"],
            "material_revision": revision(
                {
                    "slot_names": expected_names,
                    "face_material_indices": before["face_material_indices"],
                }
            ),
        }
        verification = compare(expected, self._verify_view(after))
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "before": before,
                    "after": after,
                    "source_slot_index": action.source_slot_index,
                    "new_material_name": action.new_material_name,
                },
                verification=verification.to_dict(),
            )

        obj.data.materials.pop(index=len(obj.data.materials) - 1)
        if duplicate.users == 0:
            self.bpy.data.materials.remove(duplicate)
        self.bpy.context.view_layer.update()
        restored = self._snapshot(obj)
        recovery = compare(self._verify_view(before), self._verify_view(restored))
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material duplicate verification failed and recovery could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "rolled_back": True,
                "recovery_verified": True,
                "object_before": object_before,
            },
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material duplicate readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def slot_remove(self, request: Request, action: MaterialSlotRemove):
        obj, object_before, before = self._editable(action)
        if action.slot_index >= before["slot_count"]:
            raise invalid("Material slot index does not exist")
        if action.slot_index != before["slot_count"] - 1:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Only the final material slot can be removed safely",
            )
        if before["slot_face_users"][action.slot_index] != 0:
            raise AgentError(
                ErrorCode.SAFETY_DENIED,
                "Assigned material slot cannot be removed",
            )
        removed = obj.data.materials[action.slot_index]

        obj.data.materials.pop(index=action.slot_index)
        self.bpy.context.view_layer.update()
        after = self._snapshot(obj)
        expected_names = before["slot_names"][:-1]
        expected = {
            "slot_count": before["slot_count"] - 1,
            "slot_names": expected_names,
            "face_material_indices": before["face_material_indices"],
            "material_revision": revision(
                {
                    "slot_names": expected_names,
                    "face_material_indices": before["face_material_indices"],
                }
            ),
        }
        verification = compare(expected, self._verify_view(after))
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {"before": before, "after": after, "removed_slot_index": action.slot_index},
                verification=verification.to_dict(),
            )

        obj.data.materials.append(removed)
        self.bpy.context.view_layer.update()
        restored = self._snapshot(obj)
        recovery = compare(self._verify_view(before), self._verify_view(restored))
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material remove verification failed and recovery could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "rolled_back": True,
                "recovery_verified": True,
                "object_before": object_before,
            },
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material remove readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def face_assign(self, request: Request, action: MaterialFaceAssign):
        obj, object_before, before = self._editable(action)
        if action.slot_index >= before["slot_count"]:
            raise invalid("Material slot index does not exist")
        if any(index >= before["face_count"] for index in action.face_indices):
            raise invalid("Material face index does not exist")
        previous = {
            index: int(getattr(obj.data.polygons[index], "material_index", 0))
            for index in action.face_indices
        }
        expected_face_indices = list(before["face_material_indices"])
        for index in action.face_indices:
            expected_face_indices[index] = action.slot_index
            obj.data.polygons[index].material_index = action.slot_index

        obj.data.update()
        self.bpy.context.view_layer.update()
        after = self._snapshot(obj)
        expected = {
            "slot_count": before["slot_count"],
            "slot_names": before["slot_names"],
            "face_material_indices": expected_face_indices,
            "material_revision": revision(
                {
                    "slot_names": before["slot_names"],
                    "face_material_indices": expected_face_indices,
                }
            ),
        }
        verification = compare(expected, self._verify_view(after))
        if verification.matched:
            return Result(
                request.request_id,
                request.command_id,
                Status.VERIFIED,
                {
                    "before": before,
                    "after": after,
                    "slot_index": action.slot_index,
                    "face_indices": list(action.face_indices),
                },
                verification=verification.to_dict(),
            )

        for index, value in previous.items():
            obj.data.polygons[index].material_index = value
        obj.data.update()
        self.bpy.context.view_layer.update()
        restored = self._snapshot(obj)
        recovery = compare(self._verify_view(before), self._verify_view(restored))
        if not recovery.matched:
            raise AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material face assignment failed and recovery could not be verified",
            )
        return Result(
            request.request_id,
            request.command_id,
            Status.FAILED,
            {
                "before": before,
                "after": after,
                "restored": restored,
                "rolled_back": True,
                "recovery_verified": True,
                "object_before": object_before,
            },
            AgentError(
                ErrorCode.VERIFICATION_FAILED,
                "Material face assignment readback differs from requested state",
            ),
            verification.to_dict(),
        )

    def tools(self):
        def parse_id(data):
            fields(data, {"object_id"})
            return string(data["object_id"], "object_id", limit=128)

        return [
            Tool("material.slots_inspect", SafetyClass.READ_ONLY, parse_id, self.inspect),
            Tool("material.slot_link", SafetyClass.MUTATION, MaterialSlotLink.parse, self.slot_link),
            Tool(
                "material.slot_reassign",
                SafetyClass.MUTATION,
                MaterialSlotReassign.parse,
                self.slot_reassign,
            ),
            Tool(
                "material.slot_duplicate",
                SafetyClass.MUTATION,
                MaterialSlotDuplicate.parse,
                self.slot_duplicate,
            ),
            Tool(
                "material.slot_remove",
                SafetyClass.MUTATION,
                MaterialSlotRemove.parse,
                self.slot_remove,
            ),
            Tool(
                "material.face_assign",
                SafetyClass.MUTATION,
                MaterialFaceAssign.parse,
                self.face_assign,
            ),
        ]
