from types import SimpleNamespace as NS

import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.material_nodes import MaterialNodeOperations
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.texture_workflows import (
    AssetScope,
    BakePrep,
    ImageInspect,
    MaterialOnly,
    RecoveryRestore,
    TextureWorkflowOperations,
    UDIMPlan,
)
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    objects = ObjectOperations(inspector)
    nodes = MaterialNodeOperations(objects)
    texture = TextureWorkflowOperations(objects)
    registry = ToolRegistry(
        [*nodes.tools(), *texture.tools()],
        SafetyPolicy(allow_mutations=True),
    )
    obj = bpy.data.objects.get("Cube")
    obj.data.from_pydata(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        [],
        [[0, 1, 2, 3]],
    )
    layer = obj.data.uv_layers.new("UVMap")
    for item, uv in zip(
        layer.data,
        [[0, 0], [1, 0], [1, 1], [0, 1]],
        strict=True,
    ):
        item.uv = uv
    material = bpy.data.materials.new("Surface")
    material.use_nodes = True
    obj.data.materials.append(material)
    return bpy, inspector, texture, registry, obj, material


def make_image(bpy, name, colorspace, size=(1024, 1024)):
    image = bpy.data.images.new(name, width=size[0], height=size[1])
    image.colorspace_settings.name = colorspace
    return image


def shader_revision(texture, material):
    return texture._snapshot(material)["shader_revision"]


def assign(registry, texture, material, channel, image):
    return registry.dispatch(
        Request(
            "material.pbr_texture_assign",
            {
                "material_name": material.name,
                "expected_shader_revision": shader_revision(texture, material),
                "channel": channel,
                "image_name": image.name,
            },
        )
    )


def scope(inspector, obj, material):
    return {
        "object_id": inspector.identity(obj),
        "material_name": material.name,
        "uv_layer_name": "UVMap",
    }


def test_image_inspect_reports_bounded_metadata_and_udim_tiles():
    bpy, inspector, texture, registry, obj, material = setup()
    image = make_image(bpy, "Tiles", "sRGB", (2048, 2048))
    image.source = "TILED"
    image.tiles = [NS(number=1001), NS(number=1002)]
    image.filepath = "//textures/Tiles.<UDIM>.png"
    image.packed_file = object()

    result = registry.dispatch(Request("texture.image_inspect", {"image_name": "Tiles"}))
    assert result.status == Status.SUCCEEDED
    assert result.data["size"] == [2048, 2048]
    assert result.data["colorspace"] == "sRGB"
    assert result.data["is_tiled"] is True
    assert result.data["tile_numbers"] == [1001, 1002]
    assert result.data["packed"] is True
    assert result.data["has_filepath"] is True
    assert len(result.data["image_revision"]) == 64


def test_udim_plan_keeps_exact_zero_to_one_face_in_tile_1001():
    bpy, inspector, texture, registry, obj, material = setup()

    result = registry.dispatch(
        Request(
            "texture.udim_plan",
            {"object_id": inspector.identity(obj), "uv_layer_name": "UVMap"},
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["tiles"] == [1001]
    assert result.data["face_tiles"] == [{"face_index": 0, "tile": 1001}]
    assert result.data["split_face_indices"] == []
    assert result.data["invalid_face_indices"] == []
    assert result.data["runtime_udim_verified"] is False


def test_udim_plan_reports_face_spanning_tile_boundary():
    bpy, inspector, texture, registry, obj, material = setup()
    values = [[0.5, 0], [1.5, 0], [1.5, 1], [0.5, 1]]
    for item, uv in zip(obj.data.uv_layers.active.data, values, strict=True):
        item.uv = uv

    result = registry.dispatch(
        Request(
            "texture.udim_plan",
            {"object_id": inspector.identity(obj), "uv_layer_name": "UVMap"},
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["split_face_indices"] == [0]
    assert result.data["face_tiles"][0]["tile"] is None


def test_channel_qa_passes_valid_managed_texture_and_detects_broken_link():
    bpy, inspector, texture, registry, obj, material = setup()
    image = make_image(bpy, "Base", "sRGB")
    assert assign(registry, texture, material, "BASE_COLOR", image).status == Status.VERIFIED

    clean = registry.dispatch(
        Request("texture.channel_qa", {"material_name": material.name})
    )
    assert clean.status == Status.SUCCEEDED
    assert clean.data["status"] == "PASS"
    base = next(item for item in clean.data["checks"] if item["channel"] == "BASE_COLOR")
    assert base["status"] == "PASS"

    node = material.node_tree.nodes.get("SHUVI_TEX_BASE_COLOR")
    for link in list(material.node_tree.links):
        if link.from_node is node:
            material.node_tree.links.remove(link)

    broken = registry.dispatch(
        Request("texture.channel_qa", {"material_name": material.name})
    )
    assert broken.data["status"] == "BLOCKED"
    assert "BASE_COLOR:BROKEN_CHANNEL_LINK" in broken.data["blockers"]


def test_consistency_qa_reports_mixed_texture_resolutions_without_false_block():
    bpy, inspector, texture, registry, obj, material = setup()
    base = make_image(bpy, "Base", "sRGB", (2048, 2048))
    rough = make_image(bpy, "Rough", "Non-Color", (1024, 1024))
    assert assign(registry, texture, material, "BASE_COLOR", base).status == Status.VERIFIED
    assert assign(registry, texture, material, "ROUGHNESS", rough).status == Status.VERIFIED

    result = registry.dispatch(
        Request("texture.consistency_qa", {"material_name": material.name})
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["status"] == "REVIEW"
    assert result.data["resolution_mismatch"] is True
    assert "MIXED_TEXTURE_RESOLUTIONS" in result.data["advisories"]


def test_bake_prep_is_source_only_and_ready_for_clean_asset():
    bpy, inspector, texture, registry, obj, material = setup()
    base = make_image(bpy, "Base", "sRGB")
    assert assign(registry, texture, material, "BASE_COLOR", base).status == Status.VERIFIED

    result = registry.dispatch(
        Request(
            "texture.bake_prep",
            {
                **scope(inspector, obj, material),
                "channels": ["BASE_COLOR"],
                "texture_size": 2048,
            },
        )
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["status"] == "READY"
    assert result.data["blockers"] == []
    assert result.data["udim_tiles"] == [1001]
    assert result.data["execution_status"] == "BAKE_PREP_SOURCE_ONLY"
    assert result.data["runtime_bake_executed"] is False


def test_bake_prep_blocks_material_not_assigned_and_split_udim():
    bpy, inspector, texture, registry, obj, material = setup()
    obj.data.materials.pop(index=0)
    values = [[0.5, 0], [1.5, 0], [1.5, 1], [0.5, 1]]
    for item, uv in zip(obj.data.uv_layers.active.data, values, strict=True):
        item.uv = uv

    result = registry.dispatch(
        Request(
            "texture.bake_prep",
            {
                **scope(inspector, obj, material),
                "channels": ["BASE_COLOR"],
                "texture_size": 1024,
            },
        )
    )
    assert result.data["status"] == "BLOCKED"
    assert "MATERIAL_NOT_ASSIGNED_TO_OBJECT" in result.data["blockers"]
    assert "UV_FACE_SPANS_MULTIPLE_UDIM_TILES" in result.data["blockers"]


def test_recovery_snapshot_and_restore_return_to_exact_managed_state():
    bpy, inspector, texture, registry, obj, material = setup()
    base = make_image(bpy, "Base", "sRGB")
    normal = make_image(bpy, "Normal", "Non-Color")
    assert assign(registry, texture, material, "BASE_COLOR", base).status == Status.VERIFIED
    assert assign(registry, texture, material, "NORMAL", normal).status == Status.VERIFIED

    snap = registry.dispatch(
        Request("texture.recovery_snapshot", {"material_name": material.name})
    )
    assert snap.status == Status.SUCCEEDED
    original_revision = snap.data["shader_revision"]

    changed = registry.dispatch(
        Request(
            "material.principled_set",
            {
                "material_name": material.name,
                "expected_shader_revision": shader_revision(texture, material),
                "settings": {"roughness": 0.1, "metallic": 0.8},
            },
        )
    )
    assert changed.status == Status.VERIFIED

    restored = registry.dispatch(
        Request(
            "texture.recovery_restore",
            {
                "material_name": material.name,
                "expected_shader_revision": shader_revision(texture, material),
                "recovery_revision": snap.data["recovery_revision"],
                "state": snap.data["state"],
            },
        )
    )
    assert restored.status == Status.VERIFIED
    assert restored.data["after"]["shader_revision"] == original_revision


def test_recovery_restore_rejects_stale_shader_revision():
    bpy, inspector, texture, registry, obj, material = setup()
    snap = registry.dispatch(
        Request("texture.recovery_snapshot", {"material_name": material.name})
    )
    shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Roughness"].default_value = 0.2

    result = registry.dispatch(
        Request(
            "texture.recovery_restore",
            {
                "material_name": material.name,
                "expected_shader_revision": snap.data["shader_revision"],
                "recovery_revision": snap.data["recovery_revision"],
                "state": snap.data["state"],
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE


def test_asset_qa_workflow_preview_and_level4_acceptance_pass_clean_textured_asset():
    bpy, inspector, texture, registry, obj, material = setup()
    base = make_image(bpy, "Base", "sRGB")
    assert assign(registry, texture, material, "BASE_COLOR", base).status == Status.VERIFIED
    payload = scope(inspector, obj, material)

    qa = registry.dispatch(Request("texture.asset_qa", payload))
    assert qa.status == Status.SUCCEEDED
    assert qa.data["status"] == "PASS"
    assert qa.data["real_runtime_verified"] is False
    assert qa.data["production_ready"] is False

    preview = registry.dispatch(Request("texture.workflow_preview", payload))
    assert preview.status == Status.SUCCEEDED
    assert len(preview.data["stages"]) == 10
    assert preview.data["auto_mutates"] is False
    assert preview.data["recommended_recovery_before_mutation"] is True

    acceptance = registry.dispatch(Request("texture.level4_acceptance", payload))
    assert acceptance.status == Status.SUCCEEDED
    assert acceptance.data["source_acceptance_status"] == "PASS"
    assert len(acceptance.data["checks"]) == 8
    assert acceptance.data["runtime_acceptance_required"] is True
    assert acceptance.data["real_runtime_verified"] is False
    assert acceptance.data["production_ready"] is False
    assert len(acceptance.data["acceptance_revision"]) == 64


def test_level4_acceptance_reviews_asset_without_managed_texture():
    bpy, inspector, texture, registry, obj, material = setup()

    result = registry.dispatch(
        Request("texture.level4_acceptance", scope(inspector, obj, material))
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["source_acceptance_status"] == "REVIEW"
    assert "managed_texture_present" in result.data["advisories"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (ImageInspect.parse, {"image_name": ""}),
        (MaterialOnly.parse, {"material_name": ""}),
        (UDIMPlan.parse, {"object_id": "id", "uv_layer_name": ""}),
        (
            BakePrep.parse,
            {
                "object_id": "id",
                "material_name": "Mat",
                "uv_layer_name": "UVMap",
                "channels": ["BASE_COLOR", "BASE_COLOR"],
                "texture_size": 1024,
            },
        ),
        (
            AssetScope.parse,
            {"object_id": "", "material_name": "Mat", "uv_layer_name": "UVMap"},
        ),
        (
            RecoveryRestore.parse,
            {
                "material_name": "Mat",
                "expected_shader_revision": "x" * 64,
                "recovery_revision": "y" * 64,
                "state": {
                    "principled": {
                        "base_color": [0.8, 0.8, 0.8, 1],
                        "metallic": 0,
                        "roughness": 0.5,
                        "transmission": 0,
                        "emission_color": [0, 0, 0, 1],
                        "emission_strength": 0,
                        "alpha": 1,
                    },
                    "auxiliary": {
                        "normal_strength": None,
                        "height_strength": None,
                        "height_distance": None,
                    },
                    "textures": {channel: None for channel in (
                        "BASE_COLOR",
                        "ROUGHNESS",
                        "METALLIC",
                        "NORMAL",
                        "HEIGHT",
                        "AO",
                        "ALPHA",
                    )},
                },
            },
        ),
    ],
)
def test_texture_workflow_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
