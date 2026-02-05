"""Tests for depth.py module."""

from include_what_costs.layout.depth import compute_depths


class TestComputeDepths:
    """Tests for compute_depths function."""

    def test_simple_chain(self, simple_chain):
        """Simple chain A -> B -> C gives depths 1, 2, 3."""
        edges, direct_includes = simple_chain
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        assert header_to_depth["A"] == 1
        assert header_to_depth["B"] == 2
        assert header_to_depth["C"] == 3

        assert headers_by_depth[1] == ["A"]
        assert headers_by_depth[2] == ["B"]
        assert headers_by_depth[3] == ["C"]

    def test_diamond_shortest_path(self, diamond_graph):
        """Diamond: D should be at depth 3 (shortest path), not 4."""
        edges, direct_includes = diamond_graph
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        assert header_to_depth["A"] == 1
        assert header_to_depth["B"] == 2
        assert header_to_depth["C"] == 2
        assert header_to_depth["D"] == 3  # Via A->B->D or A->C->D

    def test_multiple_roots(self, multiple_roots):
        """Multiple direct includes: both A and B at depth 1."""
        edges, direct_includes = multiple_roots
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        assert header_to_depth["A"] == 1
        assert header_to_depth["B"] == 1
        assert header_to_depth["C"] == 2  # Reachable from both A and B
        assert header_to_depth["D"] == 3

    def test_all_nodes_assigned_depth(self, complex_graph):
        """All nodes should be assigned exactly one depth."""
        edges, direct_includes = complex_graph
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        all_nodes = set(edges.keys())
        for children in edges.values():
            all_nodes.update(children)

        # All nodes reachable from direct_includes should have depth
        # Some may not be reachable if disconnected
        for node in direct_includes:
            assert node in header_to_depth

        # Check no node appears in multiple depth levels
        seen_nodes = set()
        for nodes in headers_by_depth.values():
            for node in nodes:
                assert node not in seen_nodes, f"{node} appears at multiple depths"
                seen_nodes.add(node)

    def test_depth_ordering(self, complex_graph):
        """Nodes at depth d > 1 must have parent at depth d-1."""
        edges, direct_includes = complex_graph
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        # Build reverse edge map
        child_to_parents: dict[str, set[str]] = {}
        for parent, children in edges.items():
            for child in children:
                if child not in child_to_parents:
                    child_to_parents[child] = set()
                child_to_parents[child].add(parent)

        # Check invariant: node at depth d > 1 has at least one parent at depth d-1
        for node, depth in header_to_depth.items():
            if depth > 1:
                parents = child_to_parents.get(node, set())
                parent_depths = {header_to_depth.get(p) for p in parents}
                assert depth - 1 in parent_depths, (
                    f"Node {node} at depth {depth} has no parent at depth {depth - 1}"
                )

    def test_empty_graph(self):
        """Empty graph returns empty results."""
        edges: dict[str, set[str]] = {}
        direct_includes: set[str] = set()
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        assert headers_by_depth == {}
        assert header_to_depth == {}

    def test_single_node(self):
        """Single node as direct include."""
        edges = {"A": set()}
        direct_includes = {"A"}
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        assert header_to_depth["A"] == 1
        assert headers_by_depth[1] == ["A"]

    def test_alphabetical_sorting(self):
        """Headers at same depth should be sorted alphabetically."""
        edges = {
            "Z": {"A", "B", "C"},
            "A": set(),
            "B": set(),
            "C": set(),
        }
        direct_includes = {"Z"}
        headers_by_depth, header_to_depth = compute_depths(edges, direct_includes)

        assert headers_by_depth[2] == ["A", "B", "C"]
