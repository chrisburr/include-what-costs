"""Tests for classify.py module."""

from include_what_costs.layout.classify import EdgeType, classify_edges
from include_what_costs.layout.depth import compute_depths


class TestClassifyEdges:
    """Tests for classify_edges function."""

    def test_tree_edge(self, simple_chain):
        """Tree edges connect adjacent depths."""
        edges, direct_includes = simple_chain
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)

        # A->B and B->C are tree edges
        assert ("A", "B") in classified[EdgeType.TREE]
        assert ("B", "C") in classified[EdgeType.TREE]

    def test_back_edge(self, back_edge_graph):
        """Back edges point to shallower depth."""
        edges, direct_includes = back_edge_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)

        # C->A is a back edge (depth 3 -> depth 1)
        assert ("C", "A") in classified[EdgeType.BACK]

    def test_same_level_edge(self, same_level_graph):
        """Same-level edges connect nodes at same depth."""
        edges, direct_includes = same_level_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)

        # B->C is same-level (both at depth 2)
        assert ("B", "C") in classified[EdgeType.SAME_LEVEL]

    def test_forward_skip_edge(self):
        """Forward skip edges skip multiple depths.

        Note: With BFS depth computation, forward skip edges don't naturally occur
        because BFS ensures shortest paths. This test uses manually constructed
        depths to verify the classification logic.
        """
        # Manually construct depths where A->D is forward skip
        edges = {
            "A": {"D"},
            "B": {"C"},
            "C": {"D"},
            "D": set(),
        }
        # Manually set depths to create forward skip scenario
        # (This wouldn't happen with BFS, but tests the classification logic)
        header_to_depth = {
            "A": 1,
            "B": 2,
            "C": 3,
            "D": 4,
        }
        classified = classify_edges(edges, header_to_depth)

        # A->D is forward skip (depth 1 -> depth 4)
        assert ("A", "D") in classified[EdgeType.FORWARD_SKIP]

    def test_all_edges_classified(self, complex_graph):
        """Every edge should be classified into exactly one type."""
        edges, direct_includes = complex_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)

        # Count total classified edges
        total_classified = sum(len(edge_list) for edge_list in classified.values())

        # Count total edges in original graph (only those with known depths)
        total_edges = 0
        for parent, children in edges.items():
            if parent in header_to_depth:
                for child in children:
                    if child in header_to_depth:
                        total_edges += 1

        assert total_classified == total_edges

    def test_empty_graph(self):
        """Empty graph returns empty classification."""
        edges: dict[str, set[str]] = {}
        header_to_depth: dict[str, int] = {}
        classified = classify_edges(edges, header_to_depth)

        for edge_type in EdgeType:
            assert classified[edge_type] == []

    def test_classification_correctness(self, diamond_graph):
        """Diamond graph should have only tree edges."""
        edges, direct_includes = diamond_graph
        _, header_to_depth = compute_depths(edges, direct_includes)
        classified = classify_edges(edges, header_to_depth)

        # All edges should be tree edges
        assert len(classified[EdgeType.TREE]) == 4  # A->B, A->C, B->D, C->D
        assert len(classified[EdgeType.BACK]) == 0
        assert len(classified[EdgeType.SAME_LEVEL]) == 0
        assert len(classified[EdgeType.FORWARD_SKIP]) == 0
