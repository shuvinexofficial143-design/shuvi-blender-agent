"""Read-only bpy adapter with session identities and bounded serialized results."""

import json
from hashlib import sha256
from itertools import islice
from uuid import uuid4

from .animation_state import animation_snapshot
from .contracts import Request, Result, Status
from .errors import AgentError, ErrorCode
from .models import ObjectTarget, PageQuery
from .object_state import constraints, data_summary, properties
from .safety import SafetyClass, require_revision
from .scene_state import cursor_snapshot, unit_snapshot
from .selection import selection_state
from .tools import Tool
from .validation import encode, fields, string

MAX_SCENE_OBJECTS = 10_000
MAX_DETAILS = 64
MAX_SCENE_COLLECTIONS = 10_000
MAX_INSPECTION_WORK = 100_000
MAX_PAGE_BYTES = 524_288


def bounded_text(value, *, limit=1000):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Scene text exceeds inspection bounds")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise AgentError(ErrorCode.SAFETY_DENIED, "Scene text contains invalid Unicode") from exc
    return value


def check_text(data):
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                bounded_text(value, limit=4096 if key in ("file", "filepath") else 1000)
            else:
                check_text(value)
    elif isinstance(data, list):
        for value in data:
            if isinstance(value, str):
                bounded_text(value)
            else:
                check_text(value)


def render_snapshot(scene) -> dict:
    render = scene.render
    cycles = getattr(scene, "cycles", None)
    return {
        "engine": render.engine,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "fps": render.fps,
        "fps_base": render.fps_base,
        "filepath": render.filepath,
        "format": render.image_settings.file_format,
        "color_mode": getattr(render.image_settings, "color_mode", None),
        "color_depth": getattr(render.image_settings, "color_depth", None),
        "threads_mode": getattr(render, "threads_mode", None),
        "threads": getattr(render, "threads", None),
        "cycles": {"device": cycles.device, "samples": cycles.samples} if cycles else None,
    }


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
        for obj in objects:
            bounded_text(obj.name, limit=256)
        return sorted(objects, key=lambda obj: obj.name)

    def scene_collections(self) -> list:
        collections = self.bpy.data.collections
        if len(collections) > MAX_SCENE_COLLECTIONS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Collection inspection work limit exceeded")
        for item in collections:
            bounded_text(item.name, limit=256)
        return sorted(collections, key=lambda item: item.name)

    def inspection_work(self, objects, collections):
        # Check lengths before reading nested bpy data, including animation points.
        from .animation_state import action_curves

        work = len(objects) + len(collections)
        for obj in objects:
            work += min(len(obj.modifiers), MAX_DETAILS)
            work += min(len(obj.constraints), MAX_DETAILS)
            work += min(len(obj.material_slots), MAX_DETAILS)
            work += min(len(obj.users_collection), MAX_DETAILS)
            try:
                curves = action_curves(obj)
            except AgentError:
                curves = []
            work += min(len(curves), MAX_DETAILS)
            work += sum(min(len(curve.keyframe_points), 256) for curve in islice(curves, 64))
            if work > MAX_INSPECTION_WORK:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Nested scene inspection work exceeded")
        for item in collections:
            work += len(item.objects) + len(item.children)
            if work > MAX_INSPECTION_WORK:
                raise AgentError(ErrorCode.SAFETY_DENIED, "Collection relationship work exceeded")

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
        if not object_id.startswith(self.session_id + ":"):
            raise AgentError(ErrorCode.NOT_FOUND, "Object ID belongs to another session")
        known = next((obj for uid, obj in self._identities.values() if uid == object_id), None)
        if known is not None:
            for obj in self.scene_objects():
                if obj == known and self.identity(obj) == object_id:
                    return obj
        raise AgentError(ErrorCode.NOT_FOUND, "Object ID not present in current scene/session")

    def snapshot(self, obj) -> dict:
        materials = obj.material_slots
        modifiers = obj.modifiers
        collections = obj.users_collection
        data = {
            "object_id": self.identity(obj),
            "selected": bool(obj.select_get()),
            "properties": properties(obj),
            "data": data_summary(obj),
            "constraints": constraints(obj, self),
            "constraint_count": len(obj.constraints),
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
                len(items) > MAX_DETAILS
                for items in (materials, modifiers, collections, obj.constraints)
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
        check_text(data)
        data["revision"] = revision(data)
        return data

    def scene_revision(self, snapshots, collections=None) -> str:
        scene = self.bpy.context.scene
        collections = self.scene_collections() if collections is None else collections
        metadata = {
            "file": self.bpy.data.filepath,
            "context": selection_state(self),
            "scene": scene.name,
            "cursor": cursor_snapshot(self.bpy),
            "units": unit_snapshot(scene),
            "frame": scene.frame_current,
            "frame_range": [scene.frame_start, scene.frame_end],
            "camera": self.identity(scene.camera) if scene.camera else None,
            "render": render_snapshot(scene),
            "collections": [
                {
                    "name": item.name,
                    "objects": sorted(bounded_text(obj.name, limit=256) for obj in item.objects),
                    "children": sorted(
                        bounded_text(child.name, limit=256) for child in item.children
                    ),
                }
                for item in collections
            ],
        }
        check_text(metadata)
        digest = sha256(encode(metadata))
        # Retain only one object snapshot at a time for scene revisions.
        for obj in snapshots:
            digest.update(encode({"object_id": obj["object_id"], "revision": obj["revision"]}))
        return digest.hexdigest()

    def scene_state(self):
        objects, collections = self.scene_objects(), self.scene_collections()
        self.inspection_work(objects, collections)
        return objects, collections

    def summary(self) -> dict:
        scene = self.bpy.context.scene
        objects, collections = self.scene_state()
        current_revision = self.scene_revision((self.snapshot(obj) for obj in objects), collections)
        object_counts_by_type = {}
        for obj in objects:
            object_counts_by_type[obj.type] = object_counts_by_type.get(obj.type, 0) + 1
        return {
            "session_id": self.session_id,
            "context": selection_state(self),
            "file": self.bpy.data.filepath,
            "blender_version": list(self.bpy.app.version),
            "scene": scene.name,
            "cursor": cursor_snapshot(self.bpy),
            "units": unit_snapshot(scene),
            "world_present": getattr(scene, "world", None) is not None,
            "revision": current_revision,
            "object_count": len(objects),
            "object_counts_by_type": dict(sorted(object_counts_by_type.items())),
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
            "render": render_snapshot(scene),
        }

    def page(self, query: PageQuery) -> dict:
        from dataclasses import asdict

        query = PageQuery.parse(asdict(query))
        objects, collections = self.scene_state()
        items = []
        total = 0

        def snapshots():
            nonlocal total
            for obj in objects:
                snapshot = self.snapshot(obj)
                if obj.name.startswith(query.name_prefix) and (
                    query.object_type is None or obj.type == query.object_type
                ):
                    if query.offset <= total < query.offset + query.limit:
                        items.append(snapshot)
                        if len(encode({"items": items})) > MAX_PAGE_BYTES:
                            raise AgentError(
                                ErrorCode.SAFETY_DENIED, "Page exceeds response byte limit"
                            )
                    total += 1
                yield snapshot

        current_revision = self.scene_revision(snapshots(), collections)
        if query.expected_revision is not None:
            require_revision(query.expected_revision, current_revision)
        end = query.offset + query.limit
        return {
            "session_id": self.session_id,
            "revision": current_revision,
            "total": total,
            "items": items,
            "offset": query.offset,
            "next_offset": end if end < total else None,
        }

    def collection_page(self, query: PageQuery) -> dict:
        from dataclasses import asdict

        query = PageQuery.parse(asdict(query))
        if query.object_type is not None:
            raise AgentError(ErrorCode.INVALID_REQUEST, "Collections have no object_type filter")
        objects, collections = self.scene_state()
        current = self.scene_revision((self.snapshot(obj) for obj in objects), collections)
        if query.expected_revision is not None:
            require_revision(query.expected_revision, current)
        selected = [item for item in collections if item.name.startswith(query.name_prefix)]
        end = query.offset + query.limit
        return {
            "session_id": self.session_id,
            "revision": current,
            "total": len(selected),
            "offset": query.offset,
            "next_offset": end if end < len(selected) else None,
            "items": [
                {
                    "name": item.name,
                    "object_count": len(item.objects),
                    "child_count": len(item.children),
                }
                for item in selected[query.offset : end]
            ],
        }

    def target(self, target: ObjectTarget):
        obj = self.resolve(target.object_id)
        snapshot = self.snapshot(obj)
        if obj.name != target.expected_name:
            raise AgentError(ErrorCode.STALE_STATE, "Object name changed since inspection")
        require_revision(target.expected_revision, snapshot["revision"])
        if snapshot["details_truncated"] or snapshot["animation"]["details_truncated"]:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Mutation target inspection is truncated")
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
                "collections.list",
                SafetyClass.READ_ONLY,
                PageQuery.parse,
                lambda req, page: result(req, self.collection_page(page)),
            ),
            Tool(
                "object.inspect",
                SafetyClass.READ_ONLY,
                parse_id,
                lambda req, uid: result(req, self.snapshot(self.resolve(uid))),
            ),
        ]
