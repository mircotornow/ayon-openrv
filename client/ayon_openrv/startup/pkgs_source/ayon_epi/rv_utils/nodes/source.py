from rv import commands


def set_pixel_aspect(source_node: str, pixel_aspect: float):
    """Set the given pixel aspect ratio for the given source node.

    Args:
        source_node: Node to set a pixel aspect ratio for. (Could be source node or source group node)
        pixel_aspect: Pixel aspect ratio to set.
    """
    warp_node = commands.closestNodesOfType("RVLensWarp", source_node)[0]
    commands.setFloatProperty(warp_node + ".warp.pixelAspectRatio", [pixel_aspect])
