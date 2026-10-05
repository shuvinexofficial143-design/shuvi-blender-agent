"""Bounded object property and data summaries shared by inspection and mutations."""

from itertools import islice

from .validation import integer, invalid, number

BOOLS = ("show_name", "show_bounds", "show_wire", "show_all_edges", "show_in_front")
LOCKS = ("lock_location", "lock_rotation", "lock_scale")
DISPLAYS = ("BOUNDS", "WIRE", "SOLID", "TEXTURED")
EMPTY_DISPLAYS = ("PLAIN_AXES", "ARROWS", "SINGLE_ARROW", "CIRCLE", "CUBE", "SPHERE", "CONE")


def boolean(value):
    if type(value) is not bool:
        raise invalid("Expected a boolean")
    return value


def enum(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise invalid("Unsupported enum value")
    return value


def property_values(values):
    allowed = {
        *BOOLS,
        *LOCKS,
        "display_type",
        "color",
        "pass_index",
        "empty_display_type",
        "empty_display_size",
    }
    if not isinstance(values, dict) or not values or values.keys() - allowed:
        raise invalid("Expected a nonempty allowlisted property group")
    result = {}
    for key, value in values.items():
        if key in BOOLS:
            result[key] = boolean(value)
        elif key in LOCKS:
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                raise invalid("Transform locks require three booleans")
            result[key] = [boolean(v) for v in value]
        elif key == "display_type":
            result[key] = enum(value, DISPLAYS)
        elif key == "empty_display_type":
            result[key] = enum(value, EMPTY_DISPLAYS)
        elif key == "pass_index":
            result[key] = integer(value, key, 0, 32767)
        elif key == "empty_display_size":
            result[key] = number(value, key, 0.0001, 1000)
        else:
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                raise invalid("Color requires four components")
            result[key] = [number(v, key, 0, 1) for v in value]
    return result


def properties(obj):
    result = {key: bool(getattr(obj, key, False)) for key in BOOLS}
    result.update({key: list(getattr(obj, key, (False, False, False))) for key in LOCKS})
    result.update(
        display_type=getattr(obj, "display_type", "TEXTURED"),
        color=list(getattr(obj, "color", (1, 1, 1, 1))),
        pass_index=getattr(obj, "pass_index", 0),
    )
    if obj.type == "EMPTY":
        result.update(
            empty_display_type=getattr(obj, "empty_display_type", "PLAIN_AXES"),
            empty_display_size=getattr(obj, "empty_display_size", 1.0),
        )
    return result


def data_summary(obj):
    data = obj.data
    if data is None:
        return None
    result = {
        "name": data.name,
        "object_type": obj.type,
        "users": data.users,
        "linked": getattr(data, "library", None) is not None,
    }
    if obj.type == "MESH":
        result.update(
            vertices=len(data.vertices),
            polygons=len(data.polygons),
            edges=len(getattr(data, "edges", ())),
            shape_keys=data.shape_keys is not None,
        )
    if obj.type in ("CURVE", "SURFACE", "FONT"):
        result.update(
            spline_count=len(getattr(data, "splines", ())),
            dimensions=getattr(data, "dimensions", None),
        )
    if obj.type == "FONT":
        body = data.body
        result.update(
            text_length=len(body), text_preview=body[:256], text_truncated=len(body) > 256
        )
    return result


def constraints(obj, inspector):
    return [
        {
            "name": getattr(c, "name", ""),
            "type": getattr(c, "type", "UNKNOWN"),
            "mute": bool(getattr(c, "mute", False)),
            "influence": getattr(c, "influence", None),
            "target_id": inspector.identity(c.target)
            if getattr(c, "target", None) is not None
            else None,
        }
        for c in islice(obj.constraints, 64)
    ]
