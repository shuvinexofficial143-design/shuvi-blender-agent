"""Small explicit bpy-shaped data fixture. This is not a Blender runtime emulator."""

import copy
from types import SimpleNamespace as NS


class FakeMesh:
    def __init__(self, name, table):
        self.name = name
        self.users = 0
        self.vertices = []
        self.faces = []
        self.table = table

    def from_pydata(self, vertices, edges, faces):
        self.vertices = vertices
        self.faces = faces

    def update(self):
        pass

    def copy(self):
        mesh = self.table.new(self.name + "Copy")
        mesh.vertices = copy.deepcopy(self.vertices)
        mesh.faces = copy.deepcopy(self.faces)
        return mesh


class FakeMeshes(list):
    def new(self, name):
        mesh = FakeMesh(name, self)
        self.append(mesh)
        return mesh

    def get(self, name):
        return next((item for item in self if item.name == name), None)


class FakeObjects(list):
    def new(self, name, mesh):
        obj = FakeObject(name, "MESH" if mesh is not None else "EMPTY")
        obj.data = mesh
        self.append(obj)
        return obj

    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def remove(self, obj, do_unlink=True):
        super().remove(obj)
        if do_unlink:
            for collection in obj.users_collection:
                if obj in collection.objects:
                    collection.objects.remove(obj)
        obj.data = None


class FakeLinks(list):
    def get(self, name):
        return next((obj for obj in self if obj.name == name), None)

    def link(self, obj):
        self.append(obj)
        if obj not in self.table:
            self.table.append(obj)
        obj.users_collection = [self.collection]


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
        self._data = None

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        if self._data is not None and hasattr(self._data, "users"):
            self._data.users -= 1
        self._data = value
        if value is not None and hasattr(value, "users"):
            value.users += 1

    def copy(self):
        obj = FakeObject(self.name + "Copy", self.type)
        for key in ("location", "rotation_euler", "scale", "rotation_mode", "modifiers"):
            setattr(obj, key, copy.deepcopy(getattr(self, key)))
        obj.data = self.data
        return obj

    def as_pointer(self):
        return id(self)

    def hide_get(self):
        return False


def fake_bpy(objects=None):
    objects = objects if objects is not None else [FakeObject("Cube"), FakeObject("Sphere")]
    table = FakeObjects(objects)
    objects = FakeLinks(objects)
    objects.table = table
    meshes = FakeMeshes()
    for obj in objects:
        if obj.type == "MESH":
            obj.data = meshes.new(obj.name + "Mesh")
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
    objects.collection = collection
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
        context=NS(scene=scene, mode="OBJECT", view_layer=NS(update=lambda: None)),
        data=NS(filepath="", objects=table, meshes=meshes, collections=[collection]),
        app=NS(version=(4, 2, 0)),
    )
