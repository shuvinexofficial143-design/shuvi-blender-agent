"""Bounded collection inspection and membership mutations for Level 1 control."""

from dataclasses import dataclass

from .contracts import Result, Status
from .errors import AgentError, ErrorCode
from .inspection import MAX_DETAILS, MAX_SCENE_COLLECTIONS
from .models import ObjectTarget, object_name
from .safety import SafetyClass, require_revision
from .tools import Tool
from .validation import fields, string


def _collection_name(value):
    return object_name(value)


@dataclass(frozen=True)
class CollectionNameRequest:
    name: str

    @classmethod
    def parse(cls, data):
        fields(data, {"name"})
        return cls(_collection_name(data["name"]))


@dataclass(frozen=True)
class RenameCollection:
    name: str
    new_name: str
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"name", "new_name", "expected_scene_revision"})
        return cls(
            _collection_name(data["name"]),
            _collection_name(data["new_name"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


@dataclass(frozen=True)
class CollectionObjectChange:
    collection: str
    target: ObjectTarget
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"collection", "target", "expected_scene_revision"})
        return cls(
            _collection_name(data["collection"]),
            ObjectTarget.parse(data["target"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


@dataclass(frozen=True)
class MoveObject:
    source: str
    destination: str
    target: ObjectTarget
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"source", "destination", "target", "expected_scene_revision"})
        source = _collection_name(data["source"])
        destination = _collection_name(data["destination"])
        if source == destination:
            from .validation import invalid

            raise invalid("Source and destination collections must differ")
        return cls(
            source,
            destination,
            ObjectTarget.parse(data["target"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


@dataclass(frozen=True)
class CreateChildCollection:
    name: str
    parent: str
    expected_scene_revision: str

    @classmethod
    def parse(cls, data):
        fields(data, {"name", "parent", "expected_scene_revision"})
        return cls(
            _collection_name(data["name"]),
            _collection_name(data["parent"]),
            string(data["expected_scene_revision"], "expected_scene_revision", limit=64),
        )


class CollectionOperations:
    def __init__(self, objects):
        self.objects = objects
        self.inspector = objects.inspector
        self.bpy = objects.bpy

    def _collection(self, name):
        item = self.bpy.data.collections.get(name)
        if item is None:
            raise AgentError(ErrorCode.NOT_FOUND, "Collection not found")
        return item

    def _editable_object(self, obj):
        if obj.library is not None or obj.override_library is not None or not obj.is_editable:
            raise AgentError(
                ErrorCode.SAFETY_DENIED, "Linked/overridden/read-only object cannot be relinked"
            )
        if self.bpy.context.mode != "OBJECT":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object mode required")

    def _parents(self, collection):
        parents = []
        scene_root = self.bpy.context.scene.collection
        if collection in scene_root.children:
            parents.append(scene_root.name)
        for item in self.inspector.scene_collections():
            if item != collection and collection in item.children:
                parents.append(item.name)
                if len(parents) > MAX_DETAILS:
                    break
        return sorted(set(parents))

    def summary(self, collection):
        objects = list(collection.objects)
        children = list(collection.children)
        parent_names = self._parents(collection)
        return {
            "name": collection.name,
            "object_ids": [self.inspector.identity(obj) for obj in objects[:MAX_DETAILS]],
            "object_count": len(objects),
            "child_names": sorted(child.name for child in children[:MAX_DETAILS]),
            "child_count": len(children),
            "parent_names": parent_names[:MAX_DETAILS],
            "parent_count": len(parent_names),
            "details_truncated": (
                len(objects) > MAX_DETAILS
                or len(children) > MAX_DETAILS
                or len(parent_names) > MAX_DETAILS
            ),
        }

    def inspect(self, req, action):
        data = self.summary(self._collection(action.name))
        return Result(req.request_id, req.command_id, Status.SUCCEEDED, data)

    def rename(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        collection = self._collection(action.name)
        existing = self.bpy.data.collections.get(action.new_name)
        if existing is not None and existing != collection:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Collection name already exists")
        before = self.summary(collection)
        collection.name = action.new_name
        after = self.summary(collection)
        return self.objects._result(req, before, after, {"name": action.new_name})

    def link_object(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        collection = self._collection(action.collection)
        obj, before = self.inspector.target(action.target)
        self._editable_object(obj)
        if collection in obj.users_collection:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Object is already linked to collection")
        if len(obj.users_collection) >= MAX_DETAILS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object collection membership limit reached")
        collection.objects.link(obj)
        self.bpy.context.view_layer.update()
        linked = collection in obj.users_collection and collection.objects.get(obj.name) == obj
        after = {
            "object_id": before["object_id"],
            "collection": collection.name,
            "linked": linked,
            "collection_count": len(obj.users_collection),
        }
        return self.objects._result(
            req,
            before,
            after,
            {
                "object_id": before["object_id"],
                "collection": collection.name,
                "linked": True,
                "collection_count": before["collection_count"] + 1,
            },
        )

    def unlink_object(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        collection = self._collection(action.collection)
        obj, before = self.inspector.target(action.target)
        self._editable_object(obj)
        if collection not in obj.users_collection:
            raise AgentError(ErrorCode.NOT_FOUND, "Object is not linked to collection")
        if len(obj.users_collection) <= 1:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unlink would orphan object from the scene")
        collection.objects.unlink(obj)
        self.bpy.context.view_layer.update()
        linked = collection in obj.users_collection or collection.objects.get(obj.name) == obj
        after = {
            "object_id": before["object_id"],
            "collection": collection.name,
            "linked": linked,
            "collection_count": len(obj.users_collection),
        }
        return self.objects._result(
            req,
            before,
            after,
            {
                "object_id": before["object_id"],
                "collection": collection.name,
                "linked": False,
                "collection_count": before["collection_count"] - 1,
            },
        )

    def move_object(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        source = self._collection(action.source)
        destination = self._collection(action.destination)
        obj, before = self.inspector.target(action.target)
        self._editable_object(obj)
        if source not in obj.users_collection:
            raise AgentError(ErrorCode.NOT_FOUND, "Object is not linked to source collection")
        destination_preexisting = destination in obj.users_collection
        if not destination_preexisting and len(obj.users_collection) >= MAX_DETAILS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Object collection membership limit reached")
        if not destination_preexisting:
            destination.objects.link(obj)
        source.objects.unlink(obj)
        self.bpy.context.view_layer.update()
        after = {
            "object_id": before["object_id"],
            "source": source.name,
            "destination": destination.name,
            "source_linked": source in obj.users_collection,
            "destination_linked": destination in obj.users_collection,
            "collection_count": len(obj.users_collection),
        }
        expected_count = (
            before["collection_count"]
            if not destination_preexisting
            else before["collection_count"] - 1
        )
        result = self.objects._result(
            req,
            before,
            after,
            {
                "object_id": before["object_id"],
                "source": source.name,
                "destination": destination.name,
                "source_linked": False,
                "destination_linked": True,
                "collection_count": expected_count,
            },
        )
        if result.status == Status.FAILED:
            if source not in obj.users_collection:
                source.objects.link(obj)
            if not destination_preexisting and destination in obj.users_collection:
                destination.objects.unlink(obj)
            result.data["rolled_back"] = True
        return result

    def create_child(self, req, action):
        require_revision(action.expected_scene_revision, self.inspector.summary()["revision"])
        if len(self.bpy.data.collections) >= MAX_SCENE_COLLECTIONS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Collection work limit reached")
        if self.bpy.data.collections.get(action.name) is not None:
            raise AgentError(ErrorCode.AMBIGUOUS_TARGET, "Collection name already exists")
        parent = self._collection(action.parent)
        if len(parent.children) >= MAX_DETAILS:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Parent child-collection limit reached")
        collection = self.bpy.data.collections.new(action.name)
        try:
            parent.children.link(collection)
            after = {
                "name": collection.name,
                "parent": parent.name,
                "linked": parent.children.get(collection.name) == collection,
            }
            result = self.objects._result(
                req,
                None,
                after,
                {"name": action.name, "parent": parent.name, "linked": True},
            )
            if result.status == Status.FAILED:
                self.bpy.data.collections.remove(collection)
                result.data["rolled_back"] = True
            return result
        except Exception:
            if self.bpy.data.collections.get(action.name) == collection:
                self.bpy.data.collections.remove(collection)
            raise

    def tools(self):
        return [
            Tool(
                "collection.inspect",
                SafetyClass.READ_ONLY,
                CollectionNameRequest.parse,
                self.inspect,
            ),
            Tool("collection.rename", SafetyClass.MUTATION, RenameCollection.parse, self.rename),
            Tool(
                "collection.link_object",
                SafetyClass.MUTATION,
                CollectionObjectChange.parse,
                self.link_object,
            ),
            Tool(
                "collection.unlink_object",
                SafetyClass.MUTATION,
                CollectionObjectChange.parse,
                self.unlink_object,
            ),
            Tool(
                "collection.move_object",
                SafetyClass.MUTATION,
                MoveObject.parse,
                self.move_object,
            ),
            Tool(
                "collection.create_child",
                SafetyClass.MUTATION,
                CreateChildCollection.parse,
                self.create_child,
            ),
        ]
