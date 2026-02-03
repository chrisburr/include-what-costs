"""BFS depth assignment with synthetic root."""

from collections import deque


def compute_depths(
    edges: dict[str, set[str]],
    direct_includes: set[str],
) -> tuple[dict[int, list[str]], dict[str, int]]:
    """BFS shortest-path depth assignment.

    Args:
        edges: Adjacency list (parent -> children).
        direct_includes: Headers directly included by root file (depth 1).

    Returns:
        headers_by_depth: depth -> list of headers at that depth.
        header_to_depth: header -> its depth.
    """
    header_to_depth: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()

    # All direct includes start at depth 1
    for header in direct_includes:
        header_to_depth[header] = 1
        queue.append((header, 1))

    # BFS to compute true minimum depths
    while queue:
        node, depth = queue.popleft()
        for child in edges.get(node, set()):
            if child not in header_to_depth:
                header_to_depth[child] = depth + 1
                queue.append((child, depth + 1))

    # Group headers by depth
    headers_by_depth: dict[int, list[str]] = {}
    for header, depth in header_to_depth.items():
        if depth not in headers_by_depth:
            headers_by_depth[depth] = []
        headers_by_depth[depth].append(header)

    # Sort headers alphabetically within each depth for consistent ordering
    for depth in headers_by_depth:
        headers_by_depth[depth].sort()

    return headers_by_depth, header_to_depth
