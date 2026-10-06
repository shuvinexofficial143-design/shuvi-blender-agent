"""Small explicit bpy-shaped data fixture. This is not a Blender runtime emulator."""

import copy
from types import SimpleNamespace as NS


class FakeMesh:
    def __init__(self, name, table):
        self.name = name
        self.users = 0
        self.vertices = []
        self.polygons = []
        self.shape_keys = None
        self.faces = []
        self.table = table
        self.library = None
        self.materials = FakeMaterialLinks()

    def from_pydata(self, vertices, edges, faces):
        self.vertices = [NS(co=list(vertex)) for vertex in vertices]
        self.faces = [list(face) for face in faces]
        self.polygons = [NS(vertices=list(face), use_smooth=False) for face in faces]

    def clear_geometry(self):
        self.vertices = []
        self.faces = []
        self.polygons = []

    def validate(self):
        return False

    def update(self):
        pass

    def copy(self):
        mesh = self.table.new(self.name + "Copy")
        mesh.vertices = copy.deepcopy(self.vertices)
        mesh.faces = copy.deepcopy(self.faces)
        mesh.polygons = copy.deepcopy(self.polygons)
        return mesh


class FakeMeshes(list):
    def new(self, name):
        mesh = FakeMesh(name, self)
        self.append(mesh)
        return mesh

    def get(self, name):
        return next((item for item in self if item.name == name), None)


class FakeCurvePoints(list):
    def add(self, count):
        for _ in range(count):
            self.append(NS(co=[0.0, 0.0, 0.0, 1.0]))


class FakeSpline:
    def __init__(self, spline_type):
        self.type = spline_type
        self.points = FakeCurvePoints([NS(co=[0.0, 0.0, 0.0, 1.0])])
        self.use_cyclic_u = False


class FakeSplines(list):
    def new(self, spline_type):
        spline = FakeSpline(spline_type)
        self.append(spline)
        return spline


class FakeCurveData:
    def __init__(self, name, curve_type):
        self.name = name
        self.users = 0
        self.library = None
        self.object_type = "FONT" if curve_type == "FONT" else "CURVE"
        self.dimensions = "2D"
        self.splines = FakeSplines()
        self.bevel_depth = 0.0
        self.body = ""
        self.align_x = "LEFT"
        self.size = 1.0
        self.extrude = 0.0
        self.materials = FakeMaterialLinks()


class FakeCurves(list):
    def new(self, name, type):
        data = FakeCurveData(name, type)
        self.append(data)
        return data

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
    def link(self, obj):
        if obj not in self:
            self.append(obj)
        collection = getattr(self, "default_collection", None)
        if collection is not None and collection not in obj.users_collection:
            if obj not in collection.objects:
                collection.objects.append(obj)
            obj.users_collection.append(collection)

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
        if obj not in self:
            self.append(obj)
        if obj not in self.table:
            self.table.append(obj)
        if self.collection not in obj.users_collection:
            obj.users_collection.append(self.collection)

    def unlink(self, obj):
        if obj not in self:
            raise RuntimeError("Object is not linked")
        self.remove(obj)
        if self.collection in obj.users_collection:
            obj.users_collection.remove(self.collection)


class FakeModifiers(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def new(self, name, modifier_type):
        modifier = NS(name=name, type=modifier_type, show_viewport=True, show_render=True)
        self.append(modifier)
        return modifier

    def move(self, from_index, to_index):
        item = self.pop(from_index)
        self.insert(to_index, item)


class FakeChildren(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def link(self, collection):
        if collection not in self:
            self.append(collection)

    def unlink(self, collection):
        if collection not in self:
            raise RuntimeError("Collection is not linked")
        self.remove(collection)


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
        self._hidden = False
        self._selected = False
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

    def select_get(self):
        return self._selected

    def select_set(self, value):
        self._selected = value

    def hide_set(self, value):
        self._hidden = value

    def hide_get(self):
        return self._hidden


def fake_bpy(objects=None):
    objects = objects if objects is not None else [FakeObject("Cube"), FakeObject("Sphere")]
    table = FakeObjects(objects)
    objects = FakeLinks(objects)
    objects.table = table
    meshes = FakeMeshes()
    curves = FakeCurves()
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
    table.default_collection = collection
    for obj in objects:
        obj.users_collection = [collection]
    scene = NS(
        name="Scene",
        objects=table,
        camera=None,
        frame_start=1,
        frame_end=250,
        frame_current=1,
        render=render,
        collection=collection,
        cursor=NS(location=[0.0, 0.0, 0.0]),
        unit_settings=NS(system="NONE", scale_length=1.0, length_unit="ADAPTIVE"),
        tool_settings=NS(transform_pivot_point="MEDIAN_POINT"),
    )
    table.active = None
    scene.frame_set = lambda frame: setattr(scene, "frame_current", frame)
    scene.cycles = NS(device="CPU", samples=128)
    return NS(
        context=NS(
            scene=scene,
            mode="OBJECT",
            view_layer=NS(name="ViewLayer", objects=table, update=lambda: None),
        ),
        data=NS(
            filepath="",
            objects=table,
            meshes=meshes,
            curves=curves,
            collections=collections,
            materials=FakeMaterials(),
            cameras=FakeDevices("CAMERA"),
            lights=FakeDevices("LIGHT"),
        ),
        app=NS(version=(4, 2, 0)),
    )
