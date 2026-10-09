"""Level 10 M2 — real OCEAN modifier and source-only safety verification."""

import pytest
from fake_bpy import FakeObject, fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry
from shuvi_blender_agent.vfx_ocean import OceanPreview, OceanSimulationOperations


def setup():
    object_ = FakeObject("OceanSurface", "MESH")
    bpy = fake_bpy([object_])
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(
        OceanSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )
    snap = inspector.snapshot(object_)
    data = {
        "target": {
            "object_id": snap["object_id"],
            "expected_name": snap["name"],
            "expected_revision": snap["revision"],
        },
        "name": "ShuviOcean",
        "settings": {
            "resolution": 8,
            "spatial_size": 35.0,
            "wave_scale": 1.1,
            "wave_alignment": 0.4,
            "wave_direction": 0.35,
            "choppiness": 1.5,
            "wind_velocity": 12.0,
            "random_seed": 42,
            "time": 7.0,
        },
    }
    return bpy, object_, inspector, registry, data


def preview(registry, data):
    result = registry.dispatch(Request("vfx.ocean_preview", data))
    assert result.status == Status.SUCCEEDED, result.error
    return result.data


def apply(registry, data, plan):
    return registry.dispatch(
        Request("vfx.ocean_apply", data | {"expected_ocean_revision": plan["ocean_revision"]})
    )


def release(registry, token):
    return registry.dispatch(Request("vfx.ocean_release", {"expected_ocean_token": token}))


def test_m2_ocean_generate_modifier_properties_and_safe_owned_release():
    _, obj, inspector, registry, data = setup()
    foreign = obj.modifiers.new("KeepExisting", "SUBSURF")
    data["target"]["expected_revision"] = inspector.snapshot(obj)["revision"]
    before_scene = inspector.summary()["revision"]
    plan = preview(registry, data)
    assert not plan["mutation_performed"]
    assert plan["geometry_mode"] == "GENERATE"
    assert plan["simulated_frames"] == 0
    result = apply(registry, data, plan)
    assert result.status == Status.VERIFIED, result.error
    assert result.verification["matched"]
    mod = obj.modifiers.get("ShuviOcean")
    assert mod.type == "OCEAN"
    assert mod.geometry_mode == "GENERATE"
    assert mod.resolution == 8
    assert mod.wave_scale == 1.1
    assert mod.choppiness == 1.5
    assert mod.random_seed == 42
    assert mod.time == 7.0
    assert obj.modifiers[0] is foreign
    done = release(registry, result.data["ocean_token"])
    assert done.status == Status.VERIFIED, done.error
    assert obj.modifiers == [foreign]
    assert inspector.summary()["revision"] == before_scene
    assert release(registry, result.data["ocean_token"]).error.code == ErrorCode.STALE_STATE


def test_m2_ocean_modifiers_have_independent_time_and_seed_per_object():
    obj1, obj2 = FakeObject("Sea1", "MESH"), FakeObject("Sea2", "MESH")
    bpy = fake_bpy([obj1, obj2])
    inspector = BpyInspector(bpy)
    registry = ToolRegistry(
        OceanSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=True),
    )

    def args(obj, n, time):
        snap = inspector.snapshot(obj)
        return {
            "target": {
                "object_id": snap["object_id"],
                "expected_name": snap["name"],
                "expected_revision": snap["revision"],
            },
            "name": n,
            "settings": {
                "resolution": 5,
                "spatial_size": 20,
                "wave_scale": 1,
                "wave_alignment": 0.5,
                "wave_direction": 0,
                "choppiness": 0.2,
                "wind_velocity": 6,
                "random_seed": 1,
                "time": time,
            },
        }

    first = args(obj1, "Ocean1", 3)
    created = apply(registry, first, preview(registry, first))
    assert created.status == Status.VERIFIED
    second = args(obj2, "Ocean2", 9)
    other = apply(registry, second, preview(registry, second))
    assert other.status == Status.VERIFIED
    assert obj1.modifiers[0].time == 3
    assert obj2.modifiers[0].time == 9
    assert release(registry, created.data["ocean_token"]).error.code == ErrorCode.SAFETY_DENIED
    # No cross-object adoption or unsafe cleanup when other active owned changes exist.


def test_m2_stale_input_refuses_ocean_creation():
    _, obj, _, registry, data = setup()
    plan = preview(registry, data)
    obj.modifiers.new("Foreign", "BEVEL")
    denied = apply(registry, data, plan)
    assert denied.error.code in (ErrorCode.STALE_STATE, ErrorCode.INVALID_REQUEST)
    assert obj.modifiers.get("ShuviOcean") is None


def test_m2_external_ocean_property_edit_refuses_unsafe_deletion():
    _, obj, _, registry, data = setup()
    done = apply(registry, data, preview(registry, data))
    assert done.status == Status.VERIFIED
    obj.modifiers.get("ShuviOcean").wind_velocity = 40
    denied = release(registry, done.data["ocean_token"])
    assert denied.error.code == ErrorCode.SAFETY_DENIED
    assert obj.modifiers.get("ShuviOcean").wind_velocity == 40


def test_m2_corrupted_ocean_readback_rolls_back_only_owned_modifier():
    bpy, obj, inspector, registry, data = setup()
    foreign = obj.modifiers.new("Foreign", "SOLIDIFY")
    data["target"]["expected_revision"] = inspector.snapshot(obj)["revision"]
    before = inspector.summary()["revision"]
    plan = preview(registry, data)
    calls = {"n": 0}

    def corrupt_once():
        calls["n"] += 1
        if calls["n"] == 1:
            obj.modifiers.get("ShuviOcean").wind_velocity = 99

    bpy.context.view_layer.update = corrupt_once
    denied = apply(registry, data, plan)
    assert denied.status == Status.FAILED
    assert denied.error.code == ErrorCode.VERIFICATION_FAILED
    assert obj.modifiers == [foreign]
    assert inspector.summary()["revision"] == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("resolution", 50),
        ("resolution", 4.2),
        ("time", -1),
        ("time", float("nan")),
        ("spatial_size", 10000),
        ("choppiness", -3),
        ("random_seed", True),
        ("wave_direction", 10),
        ("wind_velocity", 0),
    ],
)
def test_m2_invalid_ocean_simulation_settings_denied(key, value):
    _, _, _, _, data = setup()
    data["settings"][key] = value
    with pytest.raises(AgentError):
        OceanPreview.parse(data)


def test_m2_read_only_preview_and_mutation_permission():
    bpy, obj, inspector, _, data = setup()
    denied = ToolRegistry(
        OceanSimulationOperations(ObjectOperations(inspector)).tools(),
        SafetyPolicy(allow_mutations=False),
    )
    plan = preview(denied, data)
    assert not plan["mutation_performed"]
    assert not obj.modifiers
    assert apply(denied, data, plan).status == Status.FAILED
    assert not obj.modifiers


def test_m2_unknown_token_and_payload_extra_fields_denied():
    _, obj, _, reg, data = setup()
    with pytest.raises(AgentError):
        OceanPreview.parse(data | {"run_script": "import os"})
    assert release(reg, "unowned").error.code == ErrorCode.STALE_STATE
    assert not obj.modifiers
