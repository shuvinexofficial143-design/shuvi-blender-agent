import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.shape_ops import CreateCurve, CreateText, ShapeOperations
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(
        ShapeOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    return bpy, inspector, registry


def transform():
    return {
        "location": [1, 2, 3],
        "rotation_euler": [0.1, 0.2, 0.3],
        "scale": [1, 1, 1],
    }


def test_curve_creation_and_shape_readback():
    bpy, inspector, registry = setup()
    result = registry.dispatch(
        Request(
            "curve.create",
            {
                "name": "Path",
                "points": [[0, 0, 0], [1, 0, 0], [1, 2, 0]],
                "cyclic": True,
                "bevel_depth": 0.05,
                "transform": transform(),
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    assert result.data["after"]["shape"]["points"] == [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
    ]
    assert result.data["after"]["shape"]["cyclic"] is True
    obj = bpy.data.objects.get("Path")
    assert obj.type == "CURVE"

    readback = registry.dispatch(
        Request("shape.inspect", {"object_id": result.data["after"]["shape"]["object_id"]})
    )
    assert readback.status == Status.SUCCEEDED
    assert readback.data["point_count"] == 3


def test_text_creation_and_snapshot_summary():
    bpy, inspector, registry = setup()
    result = registry.dispatch(
        Request(
            "text.create",
            {
                "name": "Title",
                "body": "Shuvi Blender",
                "align_x": "CENTER",
                "size": 2.5,
                "extrude": 0.1,
                "transform": transform(),
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    shape = result.data["after"]["shape"]
    assert shape["body"] == "Shuvi Blender"
    assert shape["align_x"] == "CENTER"
    assert shape["size"] == 2.5
    obj = bpy.data.objects.get("Title")
    snapshot = inspector.snapshot(obj)
    assert snapshot["type"] == "FONT"
    assert snapshot["data"]["text_preview"] == "Shuvi Blender"


def test_shape_creation_rejects_stale_scene_revision():
    bpy, inspector, registry = setup()
    stale = inspector.summary()["revision"]
    bpy.context.scene.name = "Changed"
    result = registry.dispatch(
        Request(
            "curve.create",
            {
                "name": "Never",
                "points": [[0, 0, 0], [1, 0, 0]],
                "cyclic": False,
                "bevel_depth": 0,
                "transform": transform(),
                "expected_scene_revision": stale,
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE
    assert bpy.data.objects.get("Never") is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "name": "Bad",
            "points": [[0, 0, 0]],
            "cyclic": False,
            "bevel_depth": 0,
            "transform": transform(),
            "expected_scene_revision": "x" * 64,
        },
        {
            "name": "Bad",
            "points": [[0, 0, 0], [1, 0, 0]],
            "cyclic": "yes",
            "bevel_depth": 0,
            "transform": transform(),
            "expected_scene_revision": "x" * 64,
        },
    ],
)
def test_invalid_curve_payloads(payload):
    with pytest.raises(AgentError):
        CreateCurve.parse(payload)


def test_invalid_text_payloads():
    base = {
        "name": "BadText",
        "body": "Hello",
        "align_x": "LEFT",
        "size": 1,
        "extrude": 0,
        "transform": transform(),
        "expected_scene_revision": "x" * 64,
    }
    bad = dict(base)
    bad["align_x"] = "DIAGONAL"
    with pytest.raises(AgentError):
        CreateText.parse(bad)
    bad = dict(base)
    bad["body"] = "x" * 1001
    with pytest.raises(AgentError):
        CreateText.parse(bad)


def test_curve_verification_failure_cleans_created_data():
    bpy, inspector, registry = setup()

    def corrupt():
        bpy.data.objects.get("Path").data.bevel_depth = 99

    bpy.context.view_layer.update = corrupt
    result = registry.dispatch(
        Request(
            "curve.create",
            {
                "name": "Path",
                "points": [[0, 0, 0], [1, 0, 0]],
                "cyclic": False,
                "bevel_depth": 0.05,
                "transform": transform(),
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert bpy.data.objects.get("Path") is None
    assert bpy.data.curves.get("PathCurve") is None
