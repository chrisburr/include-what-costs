"""Edge classification based on depth relationships."""

from enum import Enum


class EdgeType(Enum):
    """Classification of edges based on depth relationship."""

    TREE = "tree"  # child_depth == parent_depth + 1
    BACK = "back"  # child_depth < parent_depth
    SAME_LEVEL = "same"  # child_depth == parent_depth
    FORWARD_SKIP = "skip"  # child_depth > parent_depth + 1


def classify_edges(
    edges: dict[str, set[str]],
    header_to_depth: dict[str, int],
) -> dict[EdgeType, list[tuple[str, str]]]:
    """Classify all edges by depth relationship.

    Args:
        edges: Adjacency list (parent -> children).
        header_to_depth: Mapping from header to its depth.

    Returns:
        Dictionary mapping EdgeType to list of (parent, child) tuples.
    """
    classified: dict[EdgeType, list[tuple[str, str]]] = {
        EdgeType.TREE: [],
        EdgeType.BACK: [],
        EdgeType.SAME_LEVEL: [],
        EdgeType.FORWARD_SKIP: [],
    }

    for parent, children in edges.items():
        parent_depth = header_to_depth.get(parent)
        if parent_depth is None:
            continue

        for child in children:
            child_depth = header_to_depth.get(child)
            if child_depth is None:
                continue

            if child_depth == parent_depth + 1:
                classified[EdgeType.TREE].append((parent, child))
            elif child_depth < parent_depth:
                classified[EdgeType.BACK].append((parent, child))
            elif child_depth == parent_depth:
                classified[EdgeType.SAME_LEVEL].append((parent, child))
            else:  # child_depth > parent_depth + 1
                classified[EdgeType.FORWARD_SKIP].append((parent, child))

    return classified
