import pytest
from fake_bpy import fake_bpy

from shuvi_blender_agent import AgentError, ErrorCode, Request, Status
from shuvi_blender_agent.inspection import BpyInspector
from shuvi_blender_agent.material_nodes import (
    MaterialNodeOperations,
    PBRTextureAssign,
    PBRTextureClear,
    PrincipledSet,
    ShaderInspect,
)
from shuvi_blender_agent.operations import ObjectOperations
from shuvi_blender_agent.safety import SafetyPolicy
from shuvi_blender_agent.tools import ToolRegistry


def setup():
    bpy = fake_bpy()
    inspector = BpyInspector(bpy)
    operations = MaterialNodeOperations(ObjectOperations(inspector))
    registry = ToolRegistry(operations.tools(), SafetyPolicy(allow_mutations=True))
    material = bpy.data.materials.new("Surface")
    material.use_nodes = True
    return bpy, operations, registry, material


def revision_of(operations, material):
    return operations._snapshot(material)["shader_revision"]


def test_shader_inspect_reports_principled_and_revision():
    bpy, operations, registry, material = setup()

    result = registry.dispatch(
        Request("material.shader_inspect", {"material_name": material.name})
    )
    assert result.status == Status.SUCCEEDED
    assert result.data["material_name"] == "Surface"
    assert result.data["principled"]["roughness"] == 0.5
    assert result.data["principled"]["metallic"] == 0.0
    assert result.data["node_count"] == 2
    assert len(result.data["shader_revision"]) == 64


def test_principled_set_updates_full_foundation_and_normal_chain():
    bpy, operations, registry, material = setup()
    before_revision = revision_of(operations, material)

    result = registry.dispatch(
        Request(
            "material.principled_set",
            {
                "material_name": "Surface",
                "expected_shader_revision": before_revision,
                "settings": {
                    "base_color": [0.2, 0.3, 0.4, 1],
                    "metallic": 0.8,
                    "roughness": 0.25,
                    "transmission": 0.4,
                    "emission_color": [1, 0.2, 0.1, 1],
                    "emission_strength": 2.5,
                    "alpha": 0.75,
                    "normal_strength": 0.7,
                    "height_strength": 0.35,
                    "height_distance": 0.08,
                },
            },
        )
    )
    assert result.status == Status.VERIFIED
    after = result.data["after"]
    assert after["principled"]["base_color"] == [0.2, 0.3, 0.4, 1.0]
    assert after["principled"]["transmission"] == 0.4
    assert after["principled"]["emission_strength"] == 2.5
    assert after["auxiliary"]["normal_strength"] == 0.7
    assert after["auxiliary"]["height_strength"] == 0.35
    assert ["SHUVI_NORMAL_MAP", "Normal", "SHUVI_BUMP", "Normal"] in after["links"]
    assert ["SHUVI_BUMP", "Normal", "Principled BSDF", "Normal"] in after["links"]


def test_principled_set_rejects_stale_revision():
    bpy, operations, registry, material = setup()
    stale = revision_of(operations, material)
    shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Roughness"].default_value = 0.9

    result = registry.dispatch(
        Request(
            "material.principled_set",
            {
                "material_name": "Surface",
                "expected_shader_revision": stale,
                "settings": {"roughness": 0.2},
            },
        )
    )
    assert result.error.code == ErrorCode.STALE_STATE


def test_principled_verification_failure_restores_graph():
    bpy, operations, registry, material = setup()
    before = operations._snapshot(material)
    original_update = bpy.context.view_layer.update
    calls = {"count": 0}

    def corrupt_first_update():
        calls["count"] += 1
        if calls["count"] == 1:
            shader = next(
                node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
            )
            shader.inputs["Roughness"].default_value = 0.99
        original_update()

    bpy.context.view_layer.update = corrupt_first_update
    result = registry.dispatch(
        Request(
            "material.principled_set",
            {
                "material_name": "Surface",
                "expected_shader_revision": before["shader_revision"],
                "settings": {"roughness": 0.2, "normal_strength": 0.5},
            },
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert operations._snapshot(material)["shader_revision"] == before["shader_revision"]


def make_image(bpy, name, colorspace):
    image = bpy.data.images.new(name, width=4, height=4)
    image.colorspace_settings.name = colorspace
    return image


@pytest.mark.parametrize(
    ("channel", "colorspace", "expected_wired"),
    [
        ("BASE_COLOR", "sRGB", True),
        ("ROUGHNESS", "Non-Color", True),
        ("METALLIC", "Non-Color", True),
        ("NORMAL", "Non-Color", True),
        ("HEIGHT", "Non-Color", True),
        ("AO", "Non-Color", False),
        ("ALPHA", "Non-Color", True),
    ],
)
def test_pbr_texture_assignment_enforces_channel_semantics(channel, colorspace, expected_wired):
    bpy, operations, registry, material = setup()
    image = make_image(bpy, f"{channel}_Image", colorspace)

    result = registry.dispatch(
        Request(
            "material.pbr_texture_assign",
            {
                "material_name": "Surface",
                "expected_shader_revision": revision_of(operations, material),
                "channel": channel,
                "image_name": image.name,
            },
        )
    )
    assert result.status == Status.VERIFIED
    row = result.data["after"]["textures"][channel]
    assert row["image_name"] == image.name
    assert row["colorspace"] == colorspace
    assert row["wired"] is expected_wired
    assert result.data["ao_auxiliary_only"] is (channel == "AO")


def test_normal_and_height_textures_build_bounded_chain():
    bpy, operations, registry, material = setup()
    normal = make_image(bpy, "NormalTex", "Non-Color")
    height = make_image(bpy, "HeightTex", "Non-Color")

    first = registry.dispatch(
        Request(
            "material.pbr_texture_assign",
            {
                "material_name": "Surface",
                "expected_shader_revision": revision_of(operations, material),
                "channel": "NORMAL",
                "image_name": normal.name,
            },
        )
    )
    assert first.status == Status.VERIFIED

    second = registry.dispatch(
        Request(
            "material.pbr_texture_assign",
            {
                "material_name": "Surface",
                "expected_shader_revision": revision_of(operations, material),
                "channel": "HEIGHT",
                "image_name": height.name,
            },
        )
    )
    assert second.status == Status.VERIFIED
    links = second.data["after"]["links"]
    assert ["SHUVI_TEX_NORMAL", "Color", "SHUVI_NORMAL_MAP", "Color"] in links
    assert ["SHUVI_TEX_HEIGHT", "Color", "SHUVI_BUMP", "Height"] in links
    assert ["SHUVI_NORMAL_MAP", "Normal", "SHUVI_BUMP", "Normal"] in links
    assert ["SHUVI_BUMP", "Normal", "Principled BSDF", "Normal"] in links


def test_pbr_assignment_rejects_wrong_colorspace_without_mutation():
    bpy, operations, registry, material = setup()
    image = make_image(bpy, "RoughnessWrong", "sRGB")
    before = operations._snapshot(material)

    result = registry.dispatch(
        Request(
            "material.pbr_texture_assign",
            {
                "material_name": "Surface",
                "expected_shader_revision": before["shader_revision"],
                "channel": "ROUGHNESS",
                "image_name": image.name,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert operations._snapshot(material)["shader_revision"] == before["shader_revision"]


def test_pbr_assignment_refuses_unmanaged_shader_link():
    bpy, operations, registry, material = setup()
    image = make_image(bpy, "Base", "sRGB")
    tree = material.node_tree
    shader = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
    foreign = tree.nodes.new("ShaderNodeTexImage")
    foreign.name = "FOREIGN_TEXTURE"
    tree.links.new(foreign.outputs["Color"], shader.inputs["Base Color"])
    before = operations._snapshot(material)

    result = registry.dispatch(
        Request(
            "material.pbr_texture_assign",
            {
                "material_name": "Surface",
                "expected_shader_revision": before["shader_revision"],
                "channel": "BASE_COLOR",
                "image_name": image.name,
            },
        )
    )
    assert result.error.code == ErrorCode.SAFETY_DENIED
    assert operations._snapshot(material)["shader_revision"] == before["shader_revision"]


def test_pbr_texture_clear_removes_only_managed_channel():
    bpy, operations, registry, material = setup()
    image = make_image(bpy, "Base", "sRGB")
    assigned = registry.dispatch(
        Request(
            "material.pbr_texture_assign",
            {
                "material_name": "Surface",
                "expected_shader_revision": revision_of(operations, material),
                "channel": "BASE_COLOR",
                "image_name": image.name,
            },
        )
    )
    assert assigned.status == Status.VERIFIED

    cleared = registry.dispatch(
        Request(
            "material.pbr_texture_clear",
            {
                "material_name": "Surface",
                "expected_shader_revision": revision_of(operations, material),
                "channel": "BASE_COLOR",
            },
        )
    )
    assert cleared.status == Status.VERIFIED
    assert cleared.data["after"]["textures"]["BASE_COLOR"]["node_present"] is False
    assert cleared.data["after"]["principled"]["base_color"] == [0.8, 0.8, 0.8, 1.0]


def test_pbr_assignment_verification_failure_restores_graph():
    bpy, operations, registry, material = setup()
    image = make_image(bpy, "Metal", "Non-Color")
    before = operations._snapshot(material)
    original_update = bpy.context.view_layer.update
    calls = {"count": 0}

    def corrupt_first_update():
        calls["count"] += 1
        if calls["count"] == 1:
            node = material.node_tree.nodes.get("SHUVI_TEX_METALLIC")
            node.image = None
        original_update()

    bpy.context.view_layer.update = corrupt_first_update
    result = registry.dispatch(
        Request(
            "material.pbr_texture_assign",
            {
                "material_name": "Surface",
                "expected_shader_revision": before["shader_revision"],
                "channel": "METALLIC",
                "image_name": image.name,
            },
        )
    )
    assert result.status == Status.FAILED
    assert result.error.code == ErrorCode.VERIFICATION_FAILED
    assert result.data["rolled_back"] is True
    assert result.data["recovery_verified"] is True
    assert operations._snapshot(material)["shader_revision"] == before["shader_revision"]


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (ShaderInspect.parse, {"material_name": ""}),
        (
            PrincipledSet.parse,
            {
                "material_name": "Mat",
                "expected_shader_revision": "x" * 64,
                "settings": {},
            },
        ),
        (
            PBRTextureAssign.parse,
            {
                "material_name": "Mat",
                "expected_shader_revision": "x" * 64,
                "channel": "UNKNOWN",
                "image_name": "Image",
            },
        ),
        (
            PBRTextureClear.parse,
            {
                "material_name": "Mat",
                "expected_shader_revision": "x" * 64,
                "channel": "UNKNOWN",
            },
        ),
    ],
)
def test_material_node_contracts_reject_unsafe_payloads(parser, payload):
    with pytest.raises(AgentError):
        parser(payload)
