"""Typed bounded operation payloads; units are Blender units and radians."""

from dataclasses import dataclass

from .validation import fields, integer, invalid, number, string


def vector3(value, name: str, bound: float) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise invalid(f"{name} must have exactly three components")
    return tuple(number(item, name, -bound, bound) for item in value)


@dataclass(frozen=True)
class Transform:
    location: tuple[float, float, float]
    rotation_euler: tuple[float, float, float]
    scale: tuple[float, float, float]

    def __post_init__(self):
        vector3(self.location, "location", 1_000_000)
        vector3(self.rotation_euler, "rotation_euler", 1000)
        vector3(self.scale, "scale", 10_000)

    def to_dict(self) -> dict:
        return {
            "location": list(self.location),
            "rotation_euler": list(self.rotation_euler),
            "scale": list(self.scale),
        }

    @classmethod
    def parse(cls, data: dict) -> "Transform":
        fields(data, {"location", "rotation_euler", "scale"})
        return cls(
            vector3(data["location"], "location", 1_000_000),
            vector3(data["rotation_euler"], "rotation_euler", 1000),
            vector3(data["scale"], "scale", 10_000),
        )


@dataclass(frozen=True)
class ObjectTarget:
    object_id: str
    expected_name: str
    expected_revision: str

    @classmethod
    def parse(cls, data: dict) -> "ObjectTarget":
        fields(data, {"object_id", "expected_name", "expected_revision"})
        return cls(
            string(data["object_id"], "object_id", limit=128),
            string(data["expected_name"], "expected_name"),
            string(data["expected_revision"], "expected_revision", limit=64),
        )


@dataclass(frozen=True)
class PageQuery:
    offset: int = 0
    limit: int = 25
    name_prefix: str = ""
    object_type: str | None = None
    expected_revision: str | None = None

    @classmethod
    def parse(cls, data: dict) -> "PageQuery":
        fields(data, set(), {"offset", "limit", "name_prefix", "object_type", "expected_revision"})
        prefix = data.get("name_prefix", "")
        if not isinstance(prefix, str) or len(prefix) > 256 or "\x00" in prefix:
            raise invalid("Invalid name_prefix")
        obj_type = data.get("object_type")
        if obj_type is not None:
            obj_type = string(obj_type, "object_type", limit=32)
        revision = data.get("expected_revision")
        if revision is not None:
            revision = string(revision, "expected_revision", limit=64)
        return cls(
            integer(data.get("offset", 0), "offset", 0, 10_000),
            integer(data.get("limit", 25), "limit", 1, 100),
            prefix,
            obj_type,
            revision,
        )
