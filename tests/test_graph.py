"""Tests for graph utilities."""

import pytest

from include_what_costs.graph import (
    IncludeGraph,
    build_reverse_edges,
    compute_direct_includer_counts,
)


class TestBuildReverseEdges:
    """Tests for build_reverse_edges function."""

    def test_simple_graph(self):
        """Test reverse edges for simple parent-child relationship."""
        graph = IncludeGraph()
        graph.edges["a.h"] = {"b.h", "c.h"}
        graph.edges["b.h"] = {"d.h"}
        graph.all_headers = {"a.h", "b.h", "c.h", "d.h"}

        reverse = build_reverse_edges(graph)

        assert reverse["b.h"] == {"a.h"}
        assert reverse["c.h"] == {"a.h"}
        assert reverse["d.h"] == {"b.h"}
        assert "a.h" not in reverse  # Root has no parents

    def test_multiple_parents(self):
        """Test header included by multiple parents."""
        graph = IncludeGraph()
        graph.edges["a.h"] = {"c.h"}
        graph.edges["b.h"] = {"c.h"}
        graph.all_headers = {"a.h", "b.h", "c.h"}

        reverse = build_reverse_edges(graph)

        assert reverse["c.h"] == {"a.h", "b.h"}

    def test_empty_graph(self):
        """Test empty graph returns empty reverse edges."""
        graph = IncludeGraph()

        reverse = build_reverse_edges(graph)

        assert len(reverse) == 0


class TestComputeDirectIncluderCounts:
    """Tests for compute_direct_includer_counts function."""

    def test_counts_only_prefix_matching(self):
        """Test that only prefix-matching headers are counted as includers."""
        graph = IncludeGraph()
        graph.edges["/my/code/a.h"] = {"/external/lib.h"}
        graph.edges["/my/code/b.h"] = {"/external/lib.h"}
        graph.edges["/other/code/c.h"] = {"/external/lib.h"}
        graph.all_headers = {
            "/my/code/a.h",
            "/my/code/b.h",
            "/other/code/c.h",
            "/external/lib.h",
        }

        counts = compute_direct_includer_counts(graph, ["/my/code"])

        # lib.h is included by 2 prefix-matching headers (a.h, b.h), not c.h
        assert counts["/external/lib.h"] == 2
        # a.h is not included by any prefix-matching headers
        assert counts["/my/code/a.h"] == 0

    def test_multiple_prefixes(self):
        """Test with multiple prefixes."""
        graph = IncludeGraph()
        graph.edges["/prefix1/a.h"] = {"/external/lib.h"}
        graph.edges["/prefix2/b.h"] = {"/external/lib.h"}
        graph.all_headers = {"/prefix1/a.h", "/prefix2/b.h", "/external/lib.h"}

        counts = compute_direct_includer_counts(graph, ["/prefix1", "/prefix2"])

        assert counts["/external/lib.h"] == 2

    def test_transitive_not_counted(self):
        """Test that transitive includes are not counted."""
        graph = IncludeGraph()
        # a.h -> b.h -> c.h
        graph.edges["/my/a.h"] = {"/my/b.h"}
        graph.edges["/my/b.h"] = {"/external/c.h"}
        graph.all_headers = {"/my/a.h", "/my/b.h", "/external/c.h"}

        counts = compute_direct_includer_counts(graph, ["/my"])

        # c.h is directly included by b.h only (not transitively by a.h)
        assert counts["/external/c.h"] == 1

    def test_empty_prefixes(self):
        """Test with empty prefix list returns all zeros."""
        graph = IncludeGraph()
        graph.edges["a.h"] = {"b.h"}
        graph.all_headers = {"a.h", "b.h"}

        counts = compute_direct_includer_counts(graph, [])

        assert counts["a.h"] == 0
        assert counts["b.h"] == 0
