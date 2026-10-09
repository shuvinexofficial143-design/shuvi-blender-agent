"""Level 10 M7: real Cloth pin-group binding and safe cleanup."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_cloth import ClothPreview, ClothSimulationOperations


def setup():
    cloth = FakeObject("Cape")
    bpy = fake_bpy([cloth])
    cloth.data.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0)], [], [(0, 1, 2)])
    group = cloth.vertex_groups.new(name="Shoulders")
    group.add([0, 1], 1.0, "REPLACE")
    inspector = BpyInspector(bpy)
    snap = inspector.snapshot(cloth)
    args = {
        "target": {
            "object_id": snap["object_id"],
            "expected_name": snap["name"],
            "expected_revision": snap["revision"],
        },
        "name": "PinnedCape",
        "settings": {
            "quality": 5,
            "mass": 0.3,
            "air_damping": 1.0,
            "tension_stiffness": 12,
            "bending_stiffness": 0.6,
            "self_collision": False,
            "collision_distance": 0.02,
            "pin_group": "Shoulders",
            "pin_stiffness": 35.0,
        },
    }
    reg = ToolRegistry(
        ClothSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    return cloth, group, inspector, reg, args


def preview(reg, args):
    return reg.dispatch(Request("vfx.cloth_preview", args))


def apply(reg, args, plan):
    return reg.dispatch(
        Request(
            "vfx.cloth_apply",
            args
            | {
                "expected_cloth_revision": plan.data["cloth_revision"],
            },
        )
    )


def test_m7_pin_and_release_preserve_existing_group():
    cloth, group, inspector, reg, args = setup()
    before = inspector.summary()["revision"]
    plan = preview(reg, args)
    assert plan.status == Status.SUCCEEDED
    assert plan.data["pin_group_signature"]
    done = apply(reg, args, plan)
    assert done.status == Status.VERIFIED, done.error
    mod = cloth.modifiers.get("PinnedCape")
    assert mod.settings.vertex_group_mass == "Shoulders"
    assert mod.settings.pin_stiffness == 35.0
    assert cloth.vertex_groups.get("Shoulders") is group
    released = reg.dispatch(
        Request(
            "vfx.cloth_release",
            {
                "expected_cloth_token": done.data["cloth_token"],
            },
        )
    )
    assert released.status == Status.VERIFIED, released.error
    assert not cloth.modifiers
    assert cloth.vertex_groups.get("Shoulders") is group
    assert inspector.summary()["revision"] == before


def test_m7_stale_group_weights_refused():
    cloth, group, _, reg, args = setup()
    plan = preview(reg, args)
    group.add([0], 0.2, "REPLACE")
    denied = apply(reg, args, plan)
    assert denied.error.code == ErrorCode.STALE_STATE
    assert not cloth.modifiers


def test_m7_modified_weights_prevent_release():
    cloth, group, _, reg, args = setup()
    done = apply(reg, args, preview(reg, args))
    assert done.status == Status.VERIFIED
    group.add([1], 0.5, "REPLACE")
    denied = reg.dispatch(
        Request(
            "vfx.cloth_release",
            {
                "expected_cloth_token": done.data["cloth_token"],
            },
        )
    )
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert cloth.modifiers.get("PinnedCape") is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("pin_group", "Missing"),
        ("pin_group", ""),
        ("pin_stiffness", 51),
        ("pin_stiffness", -1),
        ("pin_stiffness", float("nan")),
    ],
)
def test_m7_invalid_pin_fields(field, value):
    _, _, _, reg, args = setup()
    args["settings"][field] = value
    assert preview(reg, args).status == Status.FAILED


def test_m7_unpaired_pin_fields_rejected():
    _, _, _, _, args = setup()
    del args["settings"]["pin_stiffness"]
    with pytest.raises(AgentError):
        ClothPreview.parse(args)


def test_m7_unweighted_group_denied():
    cloth, group, _, reg, args = setup()
    group.remove([0, 1])
    assert preview(reg, args).error.code == ErrorCode.SAFETY_DENIED
    assert not cloth.modifiers


def test_m7_read_only_policy_prevents_mutation():
    cloth, group, inspector, _, args = setup()
    locked = ToolRegistry(
        ClothSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    plan = preview(locked, args)
    assert apply(locked, args, plan).status == Status.FAILED
    assert cloth.vertex_groups.get("Shoulders") is group
    assert not cloth.modifiers
