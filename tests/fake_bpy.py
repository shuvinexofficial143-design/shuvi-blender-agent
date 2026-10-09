"""Small explicit bpy-shaped data fixture. This is not a Blender runtime emulator."""

import copy
from types import SimpleNamespace as NS


class FakeVertexGroup:
    def __init__(self, owner, name, index):
        self.owner = owner
        self.name = name
        self.index = index

    def add(self, indices, weight, mode):
        if mode != "REPLACE":
            raise RuntimeError("Only REPLACE is supported in fake vertex groups")
        for index in indices:
            vertex = self.owner.data.vertices[index]
            member = next((item for item in vertex.groups if item.group == self.index), None)
            if member is None:
                vertex.groups.append(NS(group=self.index, weight=float(weight)))
            else:
                member.weight = float(weight)

    def remove(self, indices):
        for index in indices:
            vertex = self.owner.data.vertices[index]
            vertex.groups[:] = [item for item in vertex.groups if item.group != self.index]


class FakeVertexGroups(list):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def new(self, name):
        if self.get(name) is not None:
            raise RuntimeError("Vertex group already exists")
        group = FakeVertexGroup(self.owner, name, len(self))
        self.append(group)
        return group

    def remove(self, group):
        index = group.index
        for vertex in getattr(self.owner.data, "vertices", ()):
            kept = []
            for item in vertex.groups:
                if item.group == index:
                    continue
                if item.group > index:
                    item.group -= 1
                kept.append(item)
            vertex.groups[:] = kept
        super().remove(group)
        for new_index, item in enumerate(self):
            item.index = new_index


class FakeUVLayers(list):
    def __init__(self, mesh):
        super().__init__()
        self.mesh = mesh
        self.active_index = 0

    @property
    def active(self):
        if not self:
            return None
        return self[self.active_index]

    def new(self, name="UVMap"):
        loop_count = sum(len(face.vertices) for face in self.mesh.polygons)
        layer = NS(name=name, data=[NS(uv=[0.0, 0.0]) for _ in range(loop_count)])
        self.append(layer)
        self.active_index = len(self) - 1
        return layer


class FakeMesh:
    def __init__(self, name, table):
        self.name = name
        self.users = 0
        self.vertices = []
        self.edges = []
        self.polygons = []
        self.shape_keys = None
        self.faces = []
        self.uv_layers = FakeUVLayers(self)
        self.table = table
        self.library = None
        self.materials = FakeMaterialLinks()

    def from_pydata(self, vertices, edges, faces):
        self.vertices = [NS(co=list(vertex), groups=[]) for vertex in vertices]
        self.faces = [list(face) for face in faces]
        pairs = {tuple(sorted(edge)) for edge in edges}
        loop_start = 0
        polygons = []
        for face in faces:
            for index, a in enumerate(face):
                b = face[(index + 1) % len(face)]
                pairs.add(tuple(sorted((a, b))))
            polygons.append(
                NS(
                    vertices=list(face),
                    use_smooth=False,
                    material_index=0,
                    loop_start=loop_start,
                    loop_total=len(face),
                )
            )
            loop_start += len(face)
        self.edges = [NS(vertices=list(pair), use_seam=False) for pair in sorted(pairs)]
        self.polygons = polygons
        for layer in self.uv_layers:
            layer.data = [NS(uv=[0.0, 0.0]) for _ in range(loop_start)]

    def clear_geometry(self):
        self.vertices = []
        self.edges = []
        self.faces = []
        self.polygons = []
        for layer in self.uv_layers:
            layer.data = []

    def validate(self):
        return False

    def update(self):
        pass

    def copy(self):
        mesh = self.table.new(self.name + "Copy")
        mesh.vertices = copy.deepcopy(self.vertices)
        mesh.edges = copy.deepcopy(self.edges)
        mesh.faces = copy.deepcopy(self.faces)
        mesh.polygons = copy.deepcopy(self.polygons)
        for layer in self.uv_layers:
            copied = mesh.uv_layers.new(layer.name)
            copied.data = copy.deepcopy(layer.data)
        mesh.uv_layers.active_index = self.uv_layers.active_index
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


class FakeArmatureBone:
    def __init__(self, name):
        self.name = name
        self.parent = None
        self._head = [0.0, 0.0, 0.0]
        self._tail = [0.0, 0.0, 1.0]
        self.matrix_local = [[float(row == col) for col in range(4)] for row in range(4)]
        self.use_connect = False
        self.use_deform = True
        self.inherit_scale = "FULL"

    @property
    def head(self):
        return self._head

    @head.setter
    def head(self, value):
        self._head = list(value)

    @property
    def tail(self):
        return self._tail

    @tail.setter
    def tail(self, value):
        self._tail = list(value)

    @property
    def head_local(self):
        return self._head

    @property
    def tail_local(self):
        return self._tail


class FakeEditBones(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def new(self, name):
        if self.get(name) is not None:
            raise RuntimeError("Bone already exists")
        bone = FakeArmatureBone(name)
        self.append(bone)
        return bone

    def remove(self, bone):
        super().remove(bone)


class FakeArmatureData:
    def __init__(self, name):
        self.name = name
        self.users = 0
        self.library = None
        self.object_type = "ARMATURE"
        self.edit_bones = FakeEditBones()
        self.bones = self.edit_bones


class FakeArmatures(list):
    def new(self, name):
        armature = FakeArmatureData(name)
        self.append(armature)
        return armature

    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def remove(self, armature):
        super().remove(armature)


class FakeMaterialLinks(list):
    def append(self, material):
        super().append(material)
        material.users += 1

    def __setitem__(self, index, material):
        previous = self[index]
        if previous is material:
            return
        previous.users -= 1
        super().__setitem__(index, material)
        material.users += 1

    def pop(self, index=-1):
        material = super().pop(index)
        material.users -= 1
        return material


class FakeSocket:
    def __init__(
        self,
        node,
        name,
        default_value=None,
        socket_type=None,
        is_multi_input=False,
    ):
        self.node = node
        self.name = name
        self.identifier = name
        self.default_value = copy.deepcopy(default_value)
        self.type = socket_type or self._infer_type(default_value)
        self.is_multi_input = is_multi_input

    @staticmethod
    def _infer_type(value):
        if type(value) is bool:
            return "BOOLEAN"
        if type(value) is int:
            return "INT"
        if type(value) is float:
            return "VALUE"
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return "VECTOR"
        if isinstance(value, (list, tuple)) and len(value) == 4:
            return "RGBA"
        return "UNKNOWN"


class FakeSockets(dict):
    def __iter__(self):
        return iter(self.values())


class FakeNode:
    def __init__(self, node_type, name=None, bl_idname=None):
        self.type = node_type
        self.bl_idname = bl_idname or node_type
        self.name = name or node_type
        self.label = ""
        self.image = None
        self.node_tree = None
        self.location = [0.0, 0.0]
        self.blend_type = "MIX"
        self.data_type = "FLOAT"
        self.domain = "POINT"
        self.inputs = FakeSockets()
        self.outputs = FakeSockets()
        self._init_sockets()

    def _socket(
        self,
        table,
        name,
        value=None,
        socket_type=None,
        is_multi_input=False,
    ):
        table[name] = FakeSocket(
            self,
            name,
            value,
            socket_type=socket_type,
            is_multi_input=is_multi_input,
        )

    def _init_sockets(self):
        if self.type == "BSDF_PRINCIPLED":
            for name, value in (
                ("Base Color", [0.8, 0.8, 0.8, 1.0]),
                ("Metallic", 0.0),
                ("Roughness", 0.5),
                ("Transmission Weight", 0.0),
                ("Emission Color", [0.0, 0.0, 0.0, 1.0]),
                ("Emission Strength", 0.0),
                ("Alpha", 1.0),
                ("Normal", [0.0, 0.0, 0.0]),
            ):
                self._socket(self.inputs, name, value)
            self._socket(self.outputs, "BSDF")
        elif self.type == "OUTPUT_MATERIAL":
            self._socket(self.inputs, "Surface")
        elif self.type == "TEX_IMAGE":
            self._socket(self.outputs, "Color")
            self._socket(self.outputs, "Alpha")
        elif self.type == "NORMAL_MAP":
            self._socket(self.inputs, "Strength", 1.0)
            self._socket(self.inputs, "Color", [0.5, 0.5, 1.0, 1.0])
            self._socket(self.outputs, "Normal")
        elif self.type == "BUMP":
            self._socket(self.inputs, "Strength", 1.0)
            self._socket(self.inputs, "Distance", 0.1)
            self._socket(self.inputs, "Height", 0.0)
            self._socket(self.inputs, "Normal", [0.0, 0.0, 0.0])
            self._socket(self.outputs, "Normal")
        elif self.type == "MESH_CUBE":
            self._socket(self.inputs, "Size", [1.0, 1.0, 1.0])
            self._socket(self.inputs, "Vertices X", 2)
            self._socket(self.inputs, "Vertices Y", 2)
            self._socket(self.inputs, "Vertices Z", 2)
            self._socket(self.outputs, "Mesh", socket_type="GEOMETRY")
        elif self.type == "MESH_ICO_SPHERE":
            self._socket(self.inputs, "Radius", 1.0)
            self._socket(self.inputs, "Subdivisions", 2)
            self._socket(self.outputs, "Mesh", socket_type="GEOMETRY")
        elif self.type == "JOIN_GEOMETRY":
            self._socket(
                self.inputs,
                "Geometry",
                socket_type="GEOMETRY",
                is_multi_input=True,
            )
            self._socket(self.outputs, "Geometry", socket_type="GEOMETRY")
        elif self.type == "TRANSFORM_GEOMETRY":
            self._socket(self.inputs, "Geometry", socket_type="GEOMETRY")
            self._socket(self.inputs, "Translation", [0.0, 0.0, 0.0])
            self._socket(self.inputs, "Rotation", [0.0, 0.0, 0.0])
            self._socket(self.inputs, "Scale", [1.0, 1.0, 1.0])
            self._socket(self.outputs, "Geometry", socket_type="GEOMETRY")
        elif self.type == "SET_POSITION":
            self._socket(self.inputs, "Geometry", socket_type="GEOMETRY")
            self._socket(self.inputs, "Selection", True)
            self._socket(self.inputs, "Position", [0.0, 0.0, 0.0])
            self._socket(self.inputs, "Offset", [0.0, 0.0, 0.0])
            self._socket(self.outputs, "Geometry", socket_type="GEOMETRY")
        elif self.type == "INPUT_POSITION":
            self._socket(self.outputs, "Position", [0.0, 0.0, 0.0])
        elif self.type == "INPUT_NORMAL":
            self._socket(self.outputs, "Normal", [0.0, 0.0, 1.0])
        elif self.type == "INPUT_INDEX":
            self._socket(self.outputs, "Index", 0)
        elif self.type == "REALIZE_INSTANCES":
            self._socket(self.inputs, "Geometry", socket_type="GEOMETRY")
            self._socket(self.outputs, "Geometry", socket_type="GEOMETRY")
        elif self.type == "INSTANCE_ON_POINTS":
            self._socket(self.inputs, "Points", socket_type="GEOMETRY")
            self._socket(self.inputs, "Selection", True)
            self._socket(self.inputs, "Instance", socket_type="GEOMETRY")
            self._socket(self.inputs, "Pick Instance", False)
            self._socket(self.inputs, "Instance Index", 0)
            self._socket(self.inputs, "Rotation", [0.0, 0.0, 0.0])
            self._socket(self.inputs, "Scale", [1.0, 1.0, 1.0])
            self._socket(self.outputs, "Instances", socket_type="GEOMETRY")
        elif self.type == "STORE_NAMED_ATTRIBUTE":
            self._socket(self.inputs, "Geometry", socket_type="GEOMETRY")
            self._socket(self.inputs, "Selection", True)
            self._socket(self.inputs, "Name", "")
            self._socket(self.inputs, "Value", 0.0)
            self._socket(self.outputs, "Geometry", socket_type="GEOMETRY")
        elif self.type == "GROUP_OUTPUT":
            self._socket(self.inputs, "Geometry", socket_type="GEOMETRY")


class FakeNodes(list):
    TYPES = {
        "ShaderNodeBsdfPrincipled": ("BSDF_PRINCIPLED", "Principled BSDF"),
        "ShaderNodeOutputMaterial": ("OUTPUT_MATERIAL", "Material Output"),
        "ShaderNodeTexImage": ("TEX_IMAGE", "Image Texture"),
        "ShaderNodeNormalMap": ("NORMAL_MAP", "Normal Map"),
        "ShaderNodeBump": ("BUMP", "Bump"),
        "GeometryNodeMeshCube": ("MESH_CUBE", "Cube"),
        "GeometryNodeMeshIcoSphere": ("MESH_ICO_SPHERE", "Ico Sphere"),
        "GeometryNodeJoinGeometry": ("JOIN_GEOMETRY", "Join Geometry"),
        "GeometryNodeTransform": ("TRANSFORM_GEOMETRY", "Transform Geometry"),
        "GeometryNodeSetPosition": ("SET_POSITION", "Set Position"),
        "GeometryNodeInputPosition": ("INPUT_POSITION", "Position"),
        "GeometryNodeInputNormal": ("INPUT_NORMAL", "Normal"),
        "GeometryNodeInputIndex": ("INPUT_INDEX", "Index"),
        "GeometryNodeRealizeInstances": ("REALIZE_INSTANCES", "Realize Instances"),
        "GeometryNodeInstanceOnPoints": ("INSTANCE_ON_POINTS", "Instance on Points"),
        "GeometryNodeStoreNamedAttribute": ("STORE_NAMED_ATTRIBUTE", "Store Named Attribute"),
        "NodeGroupOutput": ("GROUP_OUTPUT", "Group Output"),
    }

    def new(self, node_type):
        kind, name = self.TYPES[node_type]
        node = FakeNode(kind, name, node_type)
        self.append(node)
        return node

    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def remove(self, node):
        tree = getattr(self, "tree", None)
        if tree is not None:
            for link in list(tree.links):
                if link.from_node is node or link.to_node is node:
                    tree.links.remove(link)
        super().remove(node)


class FakeNodeLinks(list):
    def new(self, from_socket, to_socket):
        link = NS(
            from_node=from_socket.node,
            from_socket=from_socket,
            to_node=to_socket.node,
            to_socket=to_socket,
        )
        self.append(link)
        return link


class FakeNodeTree:
    def __init__(self):
        self.nodes = FakeNodes()
        self.links = FakeNodeLinks()
        self.nodes.tree = self
        shader = self.nodes.new("ShaderNodeBsdfPrincipled")
        output = self.nodes.new("ShaderNodeOutputMaterial")
        self.links.new(shader.outputs["BSDF"], output.inputs["Surface"])


class FakeNodeInterface:
    def __init__(self):
        self.items_tree = []

    def new_socket(self, name, in_out, socket_type):
        item = NS(
            item_type="SOCKET",
            name=name,
            identifier=name,
            in_out=in_out,
            socket_type=socket_type,
        )
        self.items_tree.append(item)
        return item

    def remove(self, item):
        self.items_tree.remove(item)


class FakeNodeGroup:
    def __init__(self, name, tree_type):
        self.name = name
        self.bl_idname = tree_type
        self.library = None
        self.users = 0
        self.nodes = FakeNodes()
        self.links = FakeNodeLinks()
        self.nodes.tree = self
        self.interface = FakeNodeInterface()


class FakeNodeGroups(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def new(self, name, tree_type):
        group = FakeNodeGroup(name, tree_type)
        self.append(group)
        return group

    def remove(self, group):
        super().remove(group)


class FakeImages(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def new(self, name, width=1, height=1):
        image = NS(
            name=name,
            users=0,
            size=[width, height],
            library=None,
            colorspace_settings=NS(name="sRGB"),
        )
        self.append(image)
        return image


class FakeMaterials(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)

    def new(self, name):
        material = NS(
            name=name,
            users=0,
            library=None,
            use_nodes=False,
            diffuse_color=[0.8, 0.8, 0.8, 1],
            node_tree=FakeNodeTree(),
        )

        def duplicate():
            clone = self.new(material.name + "Copy")
            clone.use_nodes = material.use_nodes
            clone.diffuse_color = copy.deepcopy(material.diffuse_color)
            source_shader = next(
                node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
            )
            target_shader = next(
                node for node in clone.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
            )
            for key, value in source_shader.inputs.items():
                target_shader.inputs[key].default_value = copy.deepcopy(value.default_value)
            return clone

        material.copy = duplicate
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
            spread=3.141592653589793,
            use_shadow=True,
        )
        if self.object_type == "CAMERA":
            data.dof = NS(use_dof=False, focus_distance=10.0, focus_object=None)
            data.animation_data = None
            data.library = None

            def keyframe_insert(data_path, frame):
                if data_path not in ("lens", "dof.focus_distance"):
                    raise ValueError("Unsupported fake camera data path")
                value = data.lens if data_path == "lens" else data.dof.focus_distance
                if data.animation_data is None:
                    action = NS(name=data.name + "OpticsAction", users=1, fcurves=[])
                    data.animation_data = NS(
                        action=action, action_slot=None, drivers=[], nla_tracks=[]
                    )
                curves = data.animation_data.action.fcurves
                curve = next(
                    (item for item in curves if item.data_path == data_path),
                    None,
                )
                if curve is None:
                    curve = NS(
                        data_path=data_path,
                        array_index=0,
                        keyframe_points=FakeKeyframePoints(),
                        update=lambda: None,
                    )
                    curves.append(curve)
                curve.keyframe_points.insert(frame, value)
                return True

            def keyframe_delete(data_path, frame):
                if data.animation_data is None:
                    return False
                curves = data.animation_data.action.fcurves
                found = False
                for curve in list(curves):
                    if curve.data_path != data_path:
                        continue
                    for point in list(curve.keyframe_points):
                        if float(point.co[0]) == float(frame):
                            curve.keyframe_points.remove(point)
                            found = True
                    if not curve.keyframe_points:
                        curves.remove(curve)
                return found

            def animation_data_clear():
                data.animation_data = None

            data.keyframe_insert = keyframe_insert
            data.keyframe_delete = keyframe_delete
            data.animation_data_clear = animation_data_clear
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
        if obj.type == "ARMATURE":
            obj.pose = NS(bones=[])
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


class FakeKeyframePoints(list):
    def insert(self, frame, value=None, options=None, keyframe_type=None):
        if value is None:
            return super().insert(frame, value)
        point = NS(
            co=[float(frame), float(value)],
            interpolation="BEZIER",
            easing="AUTO",
            handle_left_type="AUTO",
            handle_right_type="AUTO",
            handle_left=[float(frame) - 1.0 / 3.0, float(value)],
            handle_right=[float(frame) + 1.0 / 3.0, float(value)],
        )
        self.append(point)
        self.sort(key=lambda item: float(item.co[0]))
        return point

    def remove(self, point, fast=False):
        super().remove(point)


class FakeNLAStrips(list):
    def new(self, name, start, action):
        frames = [float(point.co[0]) for curve in action.fcurves for point in curve.keyframe_points]
        if not frames:
            raise ValueError("NLA Action has no keys")
        first, last = min(frames), max(frames)
        strip = NS(
            name=name,
            action=action,
            frame_start=float(start),
            frame_end=float(start) + last - first,
            action_frame_start=first,
            action_frame_end=last,
            blend_type="REPLACE",
            influence=1.0,
            scale=1.0,
            repeat=1.0,
            mute=False,
        )
        self.append(strip)
        return strip


class FakeNLATracks(list):
    def new(self):
        track = NS(name="NlaTrack", mute=False, strips=FakeNLAStrips())
        self.append(track)
        return track


class FakeTimelineMarkers(list):
    """Scene timeline marker collection for API-shaped camera binding tests."""

    def new(self, name, frame=1):
        marker = NS(name=name, frame=int(frame), camera=None, select=False)
        self.append(marker)
        return marker


class FakeObjectConstraints(list):
    """Minimal object-level bpy constraint collection for camera TRACK_TO tests."""

    def new(self, type):
        if type not in ("TRACK_TO", "COPY_LOCATION"):
            raise ValueError("Fake object constraints support TRACK_TO or COPY_LOCATION only")
        constraint = NS(
            name="Track To" if type == "TRACK_TO" else "Copy Location",
            type=type,
            target=None,
            track_axis="TRACK_NEGATIVE_Z",
            up_axis="UP_Y",
            target_space="WORLD",
            owner_space="WORLD",
            use_x=True,
            use_y=True,
            use_z=True,
            invert_x=False,
            invert_y=False,
            invert_z=False,
            use_offset=False,
            influence=1.0,
            mute=False,
        )
        self.append(constraint)
        return constraint


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
        self.vertex_groups = FakeVertexGroups(self)
        self.material_slots = []
        self.animation_data = None
        self.library = None
        self.constraints = FakeObjectConstraints()
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

    def animation_data_clear(self):
        self.animation_data = None

    def keyframe_insert(self, data_path, frame):
        if self.animation_data is None:
            curves = []
            action = NS(name=self.name + "Action", users=1, fcurves=curves)
            self.animation_data = NS(
                action=action,
                action_slot=None,
                drivers=[],
                nla_tracks=FakeNLATracks(),
            )
        curves = self.animation_data.action.fcurves
        if data_path in ("hide_render", "hide_viewport"):
            values = [getattr(self, data_path)]
        elif data_path.startswith('pose.bones["') and data_path.endswith('"].influence'):
            segments = data_path.split('"')
            bone_name, constraint_name = segments[1], segments[3]
            bone = next(item for item in self.pose.bones if item.name == bone_name)
            constraint = next(item for item in bone.constraints if item.name == constraint_name)
            values = [constraint.influence]
        else:
            values = getattr(self, data_path)
        for index, value in enumerate(values):
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
                    data_path=data_path,
                    array_index=index,
                    keyframe_points=FakeKeyframePoints(),
                    update=lambda: None,
                )
                curves.append(curve)
            curve.keyframe_points.append(
                NS(
                    co=[float(frame), float(value)],
                    interpolation="BEZIER",
                    easing="AUTO",
                    handle_left_type="AUTO",
                    handle_right_type="AUTO",
                    handle_left=[float(frame) - 1.0 / 3.0, float(value)],
                    handle_right=[float(frame) + 1.0 / 3.0, float(value)],
                )
            )
        return True

    def keyframe_delete(self, data_path, frame):
        if self.animation_data is None:
            return False
        curves = self.animation_data.action.fcurves
        found = False
        for curve in list(curves):
            if curve.data_path != data_path:
                continue
            for point in list(curve.keyframe_points):
                if float(point.co[0]) == float(frame):
                    curve.keyframe_points.remove(point)
                    found = True
            if not curve.keyframe_points:
                curves.remove(curve)
        return found

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
        timeline_markers=FakeTimelineMarkers(),
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
            armatures=FakeArmatures(),
            collections=collections,
            materials=FakeMaterials(),
            images=FakeImages(),
            node_groups=FakeNodeGroups(),
            cameras=FakeDevices("CAMERA"),
            lights=FakeDevices("LIGHT"),
        ),
        app=NS(version=(4, 2, 0)),
    )
