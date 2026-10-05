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
        self.library = None
        self.materials = FakeMaterialLinks()

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


class FakeMaterialLinks(list):
    def append(self, material):
        super().append(material)
        material.users += 1

    def pop(self, index=-1):
        material = super().pop(index)
        material.users -= 1
        return material


class FakeMaterials(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def new(self, name):
        shader = NS(
            type="BSDF_PRINCIPLED",
            inputs={
                "Base Color": NS(default_value=[0.8, 0.8, 0.8, 1]),
                "Metallic": NS(default_value=0),
                "Roughness": NS(default_value=0.5),
            },
        )
        material = NS(
            name=name,
            users=0,
            use_nodes=False,
            diffuse_color=[0.8, 0.8, 0.8, 1],
            node_tree=NS(nodes=[shader]),
        )
        self.append(material)
        return material


class FakeDevices(list):
    def __init__(self, object_type):
        super().__init__()
        self.object_type = object_type

    def new(self, name, light_type=None):
        data = NS(
            name=name,
            object_type=self.object_type,
            users=0,
            type=light_type or "PERSP",
            lens=50,
            clip_start=0.1,
            clip_end=1000,
            energy=100,
            color=[1, 1, 1],
        )
        self.append(data)
        return data


class FakeObjects(list):
    def new(self, name, mesh):
        obj = FakeObject(
            name, getattr(mesh, "object_type", "MESH") if mesh is not None else "EMPTY"
        )
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
        if self.collection not in obj.users_collection:
            obj.users_collection.append(self.collection)


class FakeModifiers(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def new(self, name, modifier_type):
        modifier = NS(name=name, type=modifier_type, show_viewport=True, show_render=True)
        self.append(modifier)
        return modifier


class FakeChildren(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def link(self, collection):
        self.append(collection)


class FakeCollections(list):
    def new(self, name):
        links = FakeLinks()
        links.table = self.objects
        collection = NS(name=name, objects=links, children=FakeChildren())
        links.collection = collection
        self.append(collection)
        return collection

    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def remove(self, collection):
        super().remove(collection)
        for item in self:
            if collection in item.children:
                item.children.remove(collection)
        for obj in collection.objects:
            if collection in obj.users_collection:
                obj.users_collection.remove(collection)


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
        self.modifiers = FakeModifiers()
        self.material_slots = []
        self.animation_data = None
        self.library = None
        self.constraints = []
        self.override_library = None
        self.is_editable = True
        self.asset_data = None
        self._data = None

    @property
    def material_slots(self):
        if getattr(self, "_data", None) is not None and hasattr(self._data, "materials"):
            return [NS(material=material) for material in self._data.materials]
        return self._slots

    @material_slots.setter
    def material_slots(self, value):
        self._slots = value

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

    def asset_mark(self):
        self.asset_data = NS(description="")

    def keyframe_insert(self, data_path, frame):
        if self.animation_data is None:
            curves = []
            action = NS(name=self.name + "Action", users=1, fcurves=curves)
            self.animation_data = NS(action=action, action_slot=None, drivers=[], nla_tracks=[])
        curves = self.animation_data.action.fcurves
        for index, value in enumerate(getattr(self, data_path)):
            curve = next(
                (
                    item
                    for item in curves
                    if item.data_path == data_path and item.array_index == index
                ),
                None,
            )
            if curve is None:
                curve = NS(
                    data_path=data_path, array_index=index, keyframe_points=[], update=lambda: None
                )
                curves.append(curve)
            curve.keyframe_points.append(
                NS(co=[float(frame), float(value)], interpolation="BEZIER")
            )
        return True

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
    collection = NS(name="Collection", objects=objects, children=FakeChildren())
    collections = FakeCollections([collection])
    collections.objects = table
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
    scene.frame_set = lambda frame: setattr(scene, "frame_current", frame)
    return NS(
        context=NS(scene=scene, mode="OBJECT", view_layer=NS(update=lambda: None)),
        data=NS(
            filepath="",
            objects=table,
            meshes=meshes,
            collections=collections,
            materials=FakeMaterials(),
            cameras=FakeDevices("CAMERA"),
            lights=FakeDevices("LIGHT"),
        ),
        app=NS(version=(4, 2, 0)),
    )
