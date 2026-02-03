"""Path filtering with warning detection for external paths."""

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FilterResult:
    """Result of applying a path filter to nodes."""

    included_nodes: set[str] = field(default_factory=set)
    intermediate_nodes: set[str] = field(default_factory=set)  # Filtered-out but on path
    warnings: list[str] = field(default_factory=list)  # "Path through external: A -> B -> C"


def apply_filter(
    edges: dict[str, set[str]],
    prefixes: str | list[str],
    all_nodes: set[str] | None = None,
) -> FilterResult:
    """Filter nodes by path prefix(es), detecting paths through external headers.

    Args:
        edges: Adjacency list (parent -> children).
        prefixes: Path prefix or list of prefixes to filter by.
        all_nodes: All nodes in the graph. If None, derived from edges.

    Returns:
        FilterResult with included nodes, intermediate nodes, and warnings.
    """
    result = FilterResult()

    # Normalize to list and resolve prefixes
    if isinstance(prefixes, str):
        prefixes = [prefixes]
    resolved_prefixes = [str(Path(p).resolve()) for p in prefixes]

    # Determine all nodes
    if all_nodes is None:
        all_nodes = set(edges.keys())
        for children in edges.values():
            all_nodes.update(children)

    # Find nodes matching any of the prefixes
    for node in all_nodes:
        if any(node.startswith(p) for p in resolved_prefixes):
            result.included_nodes.add(node)

    # Build reverse edge map for path detection
    child_to_parents: dict[str, set[str]] = {}
    for parent, children in edges.items():
        for child in children:
            if child not in child_to_parents:
                child_to_parents[child] = set()
            child_to_parents[child].add(parent)

    # Find paths that go through external (filtered-out) nodes
    # A path is: included -> excluded -> ... -> included
    excluded_nodes = all_nodes - result.included_nodes

    # For each excluded node, check if it's on a path between included nodes
    for excluded in excluded_nodes:
        # Check if this excluded node has any included parent
        has_included_parent = False
        included_parents: list[str] = []
        for parent in child_to_parents.get(excluded, set()):
            if parent in result.included_nodes:
                has_included_parent = True
                included_parents.append(parent)

        if not has_included_parent:
            continue

        # BFS from this excluded node to find included descendants
        visited: set[str] = set()
        queue: deque[tuple[str, list[str]]] = deque()
        queue.append((excluded, [excluded]))

        while queue:
            node, path = queue.popleft()
            if node in visited:
                continue
            visited.add(node)

            for child in edges.get(node, set()):
                if child in result.included_nodes:
                    # Found a path: included_parent -> excluded -> ... -> included_child
                    for parent in included_parents:
                        full_path = [parent] + path + [child]
                        path_str = " -> ".join(Path(p).name for p in full_path)
                        warning = f"Path through external: {path_str}"
                        if warning not in result.warnings:
                            result.warnings.append(warning)
                        # Mark intermediate nodes
                        for intermediate in path:
                            result.intermediate_nodes.add(intermediate)
                elif child not in result.included_nodes and child not in visited:
                    queue.append((child, path + [child]))

    return result
