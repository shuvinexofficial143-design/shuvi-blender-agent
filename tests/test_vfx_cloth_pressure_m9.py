"""Level 10 M9: bounded closed-mesh CLOTH pressure RNA settings."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_cloth import ClothPreview, ClothSimulationOperations


def setup():
    fabric = FakeObject("Balloon")
    bpy = fake_bpy([fabric])
    fabric.data.from_pydata(
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
        [],
        [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)],
    )
    inspector = BpyInspector(bpy)
    snap = inspector.snapshot(fabric)
    args = {
        "target": {
            "object_id": snap["object_id"],
            "expected_name": snap["name"],
            "expected_revision": snap["revision"],
        },
        "name": "Inflatable",
        "settings": {
            "quality": 8,
            "mass": 0.4,
            "air_damping": 1.0,
            "tension_stiffness": 14,
            "bending_stiffness": 0.7,
            "self_collision": True,
            "collision_distance": 0.02,
            "pressure": {
                "force": 6.0,
                "ambient_factor": 1.25,
                "target_volume": 3.0,
                "use_target_volume": True,
            },
        },
    }
    reg = ToolRegistry(
        ClothSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    return fabric, inspector, reg, args


def preview(reg, args):
    return reg.dispatch(Request("vfx.cloth_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "vfx.cloth_apply",
            args | {"expected_cloth_revision": plan.data["cloth_revision"]},
        )
    )


def test_m9_pressure_writes_actual_blender_settings_and_releases():
    fabric, inspector, reg, args = setup()
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED, plan.error
    assert plan.data["pressure_topology_signature"]
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    mod = fabric.modifiers.get("Inflatable")
    assert mod.settings.use_pressure is True
    assert mod.settings.uniform_pressure_force == 6.0
    assert mod.settings.pressure_factor == 1.25
    assert mod.settings.target_volume == 3.0
    assert mod.settings.use_pressure_volume is True
    result = reg.dispatch(
        Request("vfx.cloth_release", {"expected_cloth_token": done.data["cloth_token"]})
    )
    assert result.status == Status.VERIFIED, result.error
    assert not fabric.modifiers
    assert inspector.summary()["revision"] == before


def test_m9_legacy_cloth_without_pressure_remains_compatible():
    fabric, _, reg, args = setup()
    del args["settings"]["pressure"]
    out = apply(reg, args, preview(reg, args))
    assert out.status == Status.VERIFIED, out.error
    assert fabric.modifiers[0].settings.use_pressure is False
    assert fabric.modifiers[0].settings.uniform_pressure_force == 0


def test_m9_open_mesh_denied_before_writes():
    fabric, _, reg, args = setup()
    fabric.data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    denied = preview(reg, args)
    assert denied.error.code in (ErrorCode.SAFETY_DENIED, ErrorCode.STALE_STATE)
    assert not fabric.modifiers


def test_m9_topology_changes_stale_plan():
    fabric, _, reg, args = setup()
    plan = preview(reg, args)
    fabric.data.polygons[0].vertices[:] = [0, 1, 2]
    assert apply(reg, args, plan).error.code == ErrorCode.SAFETY_DENIED
    assert not fabric.modifiers


def test_m9_foreign_pressure_property_edit_blocks_release():
    fabric, _, reg, args = setup()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED, done.error
    fabric.modifiers[0].settings.uniform_pressure_force = 20
    denied = reg.dispatch(
        Request("vfx.cloth_release", {"expected_cloth_token": done.data["cloth_token"]})
    )
    assert denied.error.code == ErrorCode.SAFETY_DENIED


@pytest.mark.parametrize(
    "key,value",
    [
        ("force", 101),
        ("force", -101),
        ("ambient_factor", -1),
        ("target_volume", 1001),
        ("use_target_volume", 1),
    ],
)
def test_m9_invalid_pressure_rejected(key, value):
    _, _, reg, args = setup()
    args["settings"]["pressure"][key] = value
    assert preview(reg, args).status == Status.FAILED


def test_m9_target_volume_required_when_enabled():
    _, _, _, args = setup()
    args["settings"]["pressure"]["target_volume"] = 0
    with pytest.raises(AgentError):
        ClothPreview.parse(args)


def test_m9_no_arbitrary_code_or_extra_pressure_keys():
    _, _, _, args = setup()
    args["settings"]["pressure"]["execute"] = "import bpy"
    with pytest.raises(AgentError):
        ClothPreview.parse(args)


def test_m9_read_only_mode_blocks_pressure_apply():
    fabric, inspector, _, args = setup()
    locked = ToolRegistry(
        ClothSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    plan = preview(locked, args)
    assert apply(locked, args, plan).status == Status.FAILED
    assert not fabric.modifiers
