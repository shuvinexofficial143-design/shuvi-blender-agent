"""Read action channels using legacy or slotted Blender APIs, without bpy imports."""

from itertools import islice

from .errors import AgentError, ErrorCode


def action_curves(obj):
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return []
    action = ad.action
    slot = getattr(ad, "action_slot", None)
    if slot is not None and hasattr(action, "layers"):
        if len(action.layers) != 1 or len(action.layers[0].strips) != 1:
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported layered animation structure")
        strip = action.layers[0].strips[0]
        if strip.type != "KEYFRAME":
            raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported animation strip")
        bag = strip.channelbag(slot)
        return bag.fcurves if bag is not None else []
    if not hasattr(action, "fcurves"):
        raise AgentError(ErrorCode.SAFETY_DENIED, "Unsupported action API")
    return action.fcurves


def animation_snapshot(obj) -> dict:
    ad = obj.animation_data
    result = {
        "has_animation_data": ad is not None,
        "action": ad.action.name if ad and ad.action else None,
        "channels": [],
        "details_truncated": False,
    }
    try:
        curves = action_curves(obj)
    except AgentError:
        result["unsupported_structure"] = True
        result["details_truncated"] = True
        return result
    if len(curves) > 64:
        result["details_truncated"] = True
    remaining = 1024
    for curve in islice(curves, 64):
        points = curve.keyframe_points
        count = min(remaining, 256)
        if len(points) > count:
            result["details_truncated"] = True
        result["channels"].append(
            {
                "data_path": curve.data_path,
                "index": curve.array_index,
                "point_count": len(points),
                "points": [
                    {
                        "co": list(point.co),
                        "interpolation": point.interpolation,
                        "easing": getattr(point, "easing", "AUTO"),
                        "handle_left_type": getattr(point, "handle_left_type", "AUTO"),
                        "handle_right_type": getattr(point, "handle_right_type", "AUTO"),
                        "handle_left": list(getattr(point, "handle_left", point.co)),
                        "handle_right": list(getattr(point, "handle_right", point.co)),
                    }
                    for point in islice(points, count)
                ],
            }
        )
        remaining -= min(len(points), count)
    return result
