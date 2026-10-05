from collections import Counter

import pytest
from test_operations import setup, transform

from shuvi_blender_agent import Request, Status
from shuvi_blender_agent.primitives import geometry


@pytest.mark.parametrize(
    "kind,counts",
    [
        ("UV_SPHERE", (114, 128)),
        ("ICOSPHERE", (12, 20)),
        ("CYLINDER", (32, 18)),
        ("CONE", (17, 17)),
        ("CIRCLE", (16, 1)),
        ("GRID", (81, 64)),
        ("TORUS", (128, 128)),
    ],
)
def test_expanded_primitive_readback_and_topology(kind, counts):
    bpy, inspector, registry = setup()
    result = registry.dispatch(
        Request(
            "object.create",
            {
                "name": "New",
                "kind": kind,
                "transform": transform(),
                "expected_scene_revision": inspector.summary()["revision"],
            },
        )
    )
    assert result.status == Status.VERIFIED
    mesh = bpy.data.objects.get("New").data
    assert (len(mesh.vertices), len(mesh.polygons)) == counts
    vertices, faces = geometry(kind)
    edges = Counter()
    directions = Counter()
    for face in faces:
        assert len(set(face)) == len(face)
        assert all(0 <= i < len(vertices) for i in face)
        for a, b in zip(face, (*face[1:], face[0]), strict=True):
            edges[tuple(sorted((a, b)))] += 1
            directions[a, b] += 1
    if kind not in ("CIRCLE", "GRID"):
        assert set(edges.values()) == {2}
        assert all(directions[b, a] == count for (a, b), count in directions.items())
