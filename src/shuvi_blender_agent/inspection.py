"""Read-only bpy adapter with session identities and bounded serialized results."""

import json
from hashlib import sha256
from itertools import islice
from uuid import uuid4

from .animation_state import animation_snapshot
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .models import ObjectTarget, PageQuery
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, string

MAX_SCENE_OBJECTS = 10_000
MAX_DETAILS = 64


def modifier_snapshot(mod) -> dict:
    keys = {
        "BEVEL": ("width", "segments"),
        "SUBSURF": ("levels", "render_levels"),
        "SOLIDIFY": ("thickness",),
    }.get(mod.type, ())
    return {
        "name": mod.name,
        "type": mod.type,
        "show_viewport": bool(mod.show_viewport),
        "show_render": bool(mod.show_render),
        "settings": {key: getattr(mod, key, None) for key in keys},
    }


def revision(data: dict) -> str:
    return sha256(
        json.dumps(data, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()


class BpyInspector:
    """Construct inside Blender with bpy; tests supply a bpy-shaped fake."""

    def __init__(self, bpy):
        self.bpy = bpy
        self.session_id = str(uuid4())
        self._identities: dict[int, tuple[str, object]] = {}

    def scene_objects(self) -> list:
        objects = self.bpy.context.scene.objects
        if len(objects) > MAX_SCENE_OBJECTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Scene exceeds current inspection work limit")
        return sorted(objects, key=lambda obj: obj.name)

    def identity(self, obj) -> str:
        pointer = obj.as_pointer()
        existing = self._identities.get(pointer)
        if existing is not None:
            try:
                if existing[1] == obj and existing[1].as_pointer() == pointer:
                    return existing[0]
            except ReferenceError:
                pass
        if len(self._identities) >= MAX_SCENE_OBJECTS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Session identity limit reached")
        value = f"{self.session_id}:{uuid4()}"
        self._identities[pointer] = (value, obj)
        return value

    def resolve(self, object_id: str):
        # Resolve only current-scene membership, never by name or a user-supplied pointer.
        for obj in self.scene_objects():
            if self.identity(obj) == object_id:
                return obj
        raise AgentError(ErrorCode.NOT_FOUND, "Object ID not present in current scene/session")

    def snapshot(self, obj) -> dict:
        materials = obj.material_slots
        modifiers = obj.modifiers
        collections = obj.users_collection
        data = {
            "object_id": self.identity(obj),
            "name": obj.name,
            "type": obj.type,
            "transform": {
                "location": list(obj.location),
                "rotation_mode": obj.rotation_mode,
                "rotation_euler": list(obj.rotation_euler),
                "rotation_quaternion": list(obj.rotation_quaternion),
                "rotation_axis_angle": list(obj.rotation_axis_angle),
                "scale": list(obj.scale),
            },
            "dimensions": list(obj.dimensions),
            "matrix_world": [list(row) for row in obj.matrix_world],
            "visibility": {
                "hide_viewport": bool(obj.hide_viewport),
                "hide_render": bool(obj.hide_render),
                "hidden_in_view_layer": bool(obj.hide_get()),
            },
            "parent_id": self.identity(obj.parent) if obj.parent else None,
            "collections": [collection.name for collection in collections[:MAX_DETAILS]],
            "collection_count": len(collections),
            "modifiers": [modifier_snapshot(mod) for mod in islice(modifiers, MAX_DETAILS)],
            "modifier_count": len(modifiers),
            "materials": [
                slot.material.name if slot.material else None
                for slot in islice(materials, MAX_DETAILS)
            ],
            "material_slot_count": len(materials),
            "animation": animation_snapshot(obj),
            "linked": obj.library is not None,
            "asset": {
                "marked": obj.asset_data is not None,
                "description": obj.asset_data.description if obj.asset_data else None,
            },
            "details_truncated": any(
                len(items) > MAX_DETAILS for items in (materials, modifiers, collections)
            ),
        }
        if obj.type == "CAMERA":
            data["camera"] = {
                "type": obj.data.type,
                "lens": obj.data.lens,
                "clip_start": obj.data.clip_start,
                "clip_end": obj.data.clip_end,
            }
        if obj.type == "LIGHT":
            data["light"] = {
                "type": obj.data.type,
                "energy": obj.data.energy,
                "color": list(obj.data.color),
            }
        data["revision"] = revision(data)
        return data

    def scene_revision(self, snapshots: list[dict]) -> str:
        scene = self.bpy.context.scene
        return revision(
            {
                "file": self.bpy.data.filepath,
                "scene": scene.name,
                "frame": scene.frame_current,
                "frame_range": [scene.frame_start, scene.frame_end],
                "camera": self.identity(scene.camera) if scene.camera else None,
                "render": {
                    "engine": scene.render.engine,
                    "resolution_x": scene.render.resolution_x,
                    "resolution_y": scene.render.resolution_y,
                    "filepath": scene.render.filepath,
                },
                "objects": [(obj["object_id"], obj["revision"]) for obj in snapshots],
                "collections": [
                    (item.name, len(item.objects), len(item.children))
                    for item in sorted(self.bpy.data.collections, key=lambda item: item.name)
                ],
            }
        )

    def summary(self) -> dict:
        scene = self.bpy.context.scene
        snapshots = [self.snapshot(obj) for obj in self.scene_objects()]
        collections = sorted(self.bpy.data.collections, key=lambda item: item.name)
        render = scene.render
        return {
            "session_id": self.session_id,
            "file": self.bpy.data.filepath,
            "blender_version": list(self.bpy.app.version),
            "scene": scene.name,
            "revision": self.scene_revision(snapshots),
            "object_count": len(snapshots),
            "collections": [
                {
                    "name": item.name,
                    "object_count": len(item.objects),
                    "child_count": len(item.children),
                }
                for item in collections[:MAX_DETAILS]
            ],
            "collection_count": len(collections),
            "collections_truncated": len(collections) > MAX_DETAILS,
            "camera_id": self.identity(scene.camera) if scene.camera else None,
            "frames": {
                "start": scene.frame_start,
                "end": scene.frame_end,
                "current": scene.frame_current,
            },
            "render": {
                "engine": render.engine,
                "resolution_x": render.resolution_x,
                "resolution_y": render.resolution_y,
                "resolution_percentage": render.resolution_percentage,
                "fps": render.fps,
                "fps_base": render.fps_base,
                "filepath": render.filepath,
                "format": render.image_settings.file_format,
            },
        }

    def page(self, query: PageQuery) -> dict:
        snapshots = [self.snapshot(obj) for obj in self.scene_objects()]
        current_revision = self.scene_revision(snapshots)
        if query.expected_revision is not None:
            require_revision(query.expected_revision, current_revision)
        selected = [
            obj
            for obj in snapshots
            if obj["name"].startswith(query.name_prefix)
            and (query.object_type is None or obj["type"] == query.object_type)
        ]
        end = query.offset + query.limit
        return {
            "revision": current_revision,
            "total": len(selected),
            "items": selected[query.offset : end],
            "offset": query.offset,
            "next_offset": end if end < len(selected) else None,
        }

    def target(self, target: ObjectTarget):
        obj = self.resolve(target.object_id)
        snapshot = self.snapshot(obj)
        if obj.name != target.expected_name:
            raise AgentError(ErrorCode.STALE_STATE, "Object name changed since inspection")
        require_revision(target.expected_revision, snapshot["revision"])
        return obj, snapshot

    def tools(self) -> list[Tool]:
        def result(req: Request, data: dict) -> Result:
            return Result(req.request_id, req.command_id, Status.SUCCEEDED, data)

        def parse_id(payload):
            fields(payload, {"object_id"})
            return string(payload["object_id"], "object_id", limit=128)

        return [
            Tool(
                "scene.inspect",
                SafetyClass.READ_ONLY,
                lambda p: fields(p, set()),
                lambda req, _: result(req, self.summary()),
            ),
            Tool(
                "objects.list",
                SafetyClass.READ_ONLY,
                PageQuery.parse,
                lambda req, page: result(req, self.page(page)),
            ),
            Tool(
                "object.inspect",
                SafetyClass.READ_ONLY,
                parse_id,
                lambda req, uid: result(req, self.snapshot(self.resolve(uid))),
            ),
        ]
