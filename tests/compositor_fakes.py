"""Minimal fake Blender compositor nodes used only in bounded CI unit tests."""

from types import SimpleNamespace as NS

from fake_bpy import fake_bpy


class Named(list):
    def get(self, name):
        return next((item for item in self if item.name == name), None)


class Socket:
    def __init__(self, name, default=None):
        self.name = name
        self.default_value = default


class Sockets(list):
    def __getitem__(self, key):
        if isinstance(key, str):
            return next(item for item in self if item.name == key)
        return super().__getitem__(key)


class Node:
    def __init__(self, name, kind):
        self.name = name
        self.bl_idname = kind
        self.inputs = Sockets()
        self.outputs = Sockets()
        if kind == "CompositorNodeMovieClip":
            self.clip = None
            self.outputs.append(Socket("Image"))
        elif kind == "CompositorNodeKeying":
            self.inputs.extend([Socket("Image"), Socket("Key Color", (0, 1, 0, 1))])
            self.outputs.extend([Socket("Image"), Socket("Matte")])
            self.clip_black = 0.0
            self.clip_white = 1.0
            self.despill_factor = 0.0
        elif kind == "CompositorNodeDilateErode":
            self.inputs.append(Socket("Mask"))
            self.outputs.append(Socket("Mask"))
            self.mode = "STEP"
            self.distance = 0
        elif kind == "CompositorNodeSetAlpha":
            self.inputs.extend([Socket("Image"), Socket("Alpha")])
            self.outputs.append(Socket("Image"))
            self.mode = "APPLY"
        elif kind == "CompositorNodeImage":
            self.outputs.append(Socket("Image"))
        elif kind == "CompositorNodeBrightContrast":
            self.inputs.extend([Socket("Image"), Socket("Bright", 0.0), Socket("Contrast", 0.0)])
            self.outputs.append(Socket("Image"))
            self.use_premultiply = False
        elif kind == "CompositorNodeViewer":
            self.inputs.append(Socket("Image"))
        elif kind == "CompositorNodeComposite":
            self.inputs.append(Socket("Image"))
        elif kind == "CompositorNodeAlphaOver":
            self.inputs.extend([Socket("Fac", 1.0), Socket("Image"), Socket("Image")])
            self.outputs.append(Socket("Image"))
            self.use_premultiply = False
            self.premul = 0.0
        else:
            raise ValueError(kind)


class Nodes(Named):
    def __init__(self, tree):
        super().__init__()
        self.tree = tree

    def new(self, kind):
        node = Node(kind, kind)
        self.append(node)
        return node

    def remove(self, node):
        self.tree.links[:] = [
            link
            for link in self.tree.links
            if link.from_node is not node and link.to_node is not node
        ]
        super().remove(node)


class Links(list):
    def __init__(self, tree):
        super().__init__()
        self.tree = tree

    def new(self, output, input_socket):
        from_node = next(node for node in self.tree.nodes if output in node.outputs)
        to_node = next(node for node in self.tree.nodes if input_socket in node.inputs)
        if any(item.to_socket is input_socket for item in self):
            raise RuntimeError("Existing input socket connection")
        link = NS(
            from_node=from_node,
            to_node=to_node,
            from_socket=output,
            to_socket=input_socket,
        )
        self.append(link)
        return link


class NodeTree:
    def __init__(self):
        self.nodes = Nodes(self)
        self.links = Links(self)


def setup():
    bpy = fake_bpy()
    tree = NodeTree()
    scene = NS(name="Scene", library=None, use_nodes=True, node_tree=tree)
    clip = NS(name="Footage", library=None)
    bpy.data.scenes = Named([scene])
    bpy.data.movieclips = Named([clip])
    return bpy, scene, clip, tree
