"""Small explicit bpy-shaped data fixture. This is not a Blender runtime emulator."""

from types import SimpleNamespace as NS


class FakeObject:
    def __init__(self, name, object_type="MESH"):
        self.name = name
        self.type = object_type
        self.location = [0.0, 0.0, 0.0]
        self.rotation_mode = "XYZ"
        self.rotation_euler = [0.0, 0.0, 0.0]
        self.rotation_quaternion = [1.0, 0.0, 0.0, 0.0]
        self.rotation_axis_angle = [0.0, 0.0, 1.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]
        self.dimensions = [2.0, 2.0, 2.0]
        self.matrix_world = [[float(row == col) for col in range(4)] for row in range(4)]
        self.hide_viewport = False
        self.hide_render = False
        self.parent = None
        self.users_collection = []
        self.modifiers = []
        self.material_slots = []
        self.animation_data = None
        self.library = None
        self.constraints = []
        self.override_library = None
        self.is_editable = True
        self.data = None

    def as_pointer(self):
        return id(self)

    def hide_get(self):
        return False


def fake_bpy(objects=None):
    objects = objects if objects is not None else [FakeObject("Cube"), FakeObject("Sphere")]
    render = NS(
        engine="BLENDER_EEVEE_NEXT",
        resolution_x=1920,
        resolution_y=1080,
        resolution_percentage=100,
        fps=24,
        fps_base=1.0,
        filepath="//render",
        image_settings=NS(file_format="PNG"),
    )
    collection = NS(name="Collection", objects=objects, children=[])
    for obj in objects:
        obj.users_collection = [collection]
    scene = NS(
        name="Scene",
        objects=objects,
        camera=None,
        frame_start=1,
        frame_end=250,
        frame_current=1,
        render=render,
        collection=collection,
    )
    return NS(
        context=NS(scene=scene, view_layer=NS(update=lambda: None)),
        data=NS(filepath="", objects=objects, collections=[collection]),
        app=NS(version=(4, 2, 0)),
    )
