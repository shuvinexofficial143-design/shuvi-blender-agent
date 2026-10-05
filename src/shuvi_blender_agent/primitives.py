"""Small deterministic mesh primitives, without operators or runtime imports.

Coordinates are rounded to Blender's float32 mesh storage before verification.
Circle is a filled disk; resolution is deliberately fixed and bounded.
"""

from math import cos, pi, sin, sqrt
from struct import pack, unpack

KINDS = (
    "CUBE",
    "PLANE",
    "EMPTY",
    "UV_SPHERE",
    "ICOSPHERE",
    "CYLINDER",
    "CONE",
    "CIRCLE",
    "GRID",
    "TORUS",
)


def geometry(kind):
    vertices, faces = [], []
    n = 16
    if kind == "PLANE":
        vertices = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
        faces = [(0, 1, 2, 3)]
    elif kind == "CUBE":
        vertices = [
            (-1, -1, -1),
            (1, -1, -1),
            (1, 1, -1),
            (-1, 1, -1),
            (-1, -1, 1),
            (1, -1, 1),
            (1, 1, 1),
            (-1, 1, 1),
        ]
        faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    elif kind in ("CIRCLE", "CYLINDER", "CONE"):
        vertices = [
            (cos(2 * pi * i / n), sin(2 * pi * i / n), 0 if kind == "CIRCLE" else -1)
            for i in range(n)
        ]
        faces = [tuple(range(n)) if kind == "CIRCLE" else tuple(reversed(range(n)))]
        if kind == "CYLINDER":
            vertices += [(x, y, 1) for x, y, _ in vertices]
            faces += [tuple(range(n, 2 * n))]
            faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
        elif kind == "CONE":
            vertices += [(0, 0, 1)]
            faces += [(i, (i + 1) % n, n) for i in range(n)]
    elif kind == "GRID":
        vertices = [(x / 4 - 1, y / 4 - 1, 0) for y in range(9) for x in range(9)]
        faces = [
            (y * 9 + x, y * 9 + x + 1, (y + 1) * 9 + x + 1, (y + 1) * 9 + x)
            for y in range(8)
            for x in range(8)
        ]
    elif kind == "UV_SPHERE":
        vertices = (
            [(0, 0, 1)]
            + [
                (
                    sin(pi * j / 8) * cos(2 * pi * i / n),
                    sin(pi * j / 8) * sin(2 * pi * i / n),
                    cos(pi * j / 8),
                )
                for j in range(1, 8)
                for i in range(n)
            ]
            + [(0, 0, -1)]
        )
        faces = [(0, 1 + i, 1 + (i + 1) % n) for i in range(n)]
        for j in range(6):
            faces += [
                (
                    1 + j * n + i,
                    1 + (j + 1) * n + i,
                    1 + (j + 1) * n + (i + 1) % n,
                    1 + j * n + (i + 1) % n,
                )
                for i in range(n)
            ]
        faces += [(1 + 6 * n + i, len(vertices) - 1, 1 + 6 * n + (i + 1) % n) for i in range(n)]
    elif kind == "ICOSPHERE":
        t = (1 + sqrt(5)) / 2
        vertices = [
            (-1, t, 0),
            (1, t, 0),
            (-1, -t, 0),
            (1, -t, 0),
            (0, -1, t),
            (0, 1, t),
            (0, -1, -t),
            (0, 1, -t),
            (t, 0, -1),
            (t, 0, 1),
            (-t, 0, -1),
            (-t, 0, 1),
        ]
        vertices = [tuple(c / sqrt(1 + t * t) for c in v) for v in vertices]
        faces = [
            (0, 11, 5),
            (0, 5, 1),
            (0, 1, 7),
            (0, 7, 10),
            (0, 10, 11),
            (1, 5, 9),
            (5, 11, 4),
            (11, 10, 2),
            (10, 7, 6),
            (7, 1, 8),
            (3, 9, 4),
            (3, 4, 2),
            (3, 2, 6),
            (3, 6, 8),
            (3, 8, 9),
            (4, 9, 5),
            (2, 4, 11),
            (6, 2, 10),
            (8, 6, 7),
            (9, 8, 1),
        ]
    elif kind == "TORUS":
        vertices = [
            (
                (1 + 0.25 * cos(2 * pi * j / 8)) * cos(2 * pi * i / n),
                (1 + 0.25 * cos(2 * pi * j / 8)) * sin(2 * pi * i / n),
                0.25 * sin(2 * pi * j / 8),
            )
            for i in range(n)
            for j in range(8)
        ]
        faces = [
            (i * 8 + j, ((i + 1) % n) * 8 + j, ((i + 1) % n) * 8 + (j + 1) % 8, i * 8 + (j + 1) % 8)
            for i in range(n)
            for j in range(8)
        ]
    else:
        raise ValueError("Unsupported mesh primitive")
    return [tuple(unpack("f", pack("f", c))[0] for c in v) for v in vertices], faces
