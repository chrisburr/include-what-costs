"""Tests for filter.py module."""

from include_what_costs.layout.filter import FilterResult, apply_filter


class TestApplyFilter:
    """Tests for apply_filter function."""

    def test_nodes_matching_filter_included(self):
        """Nodes matching the filter prefix should be included."""
        edges = {
            "/proj/A.h": {"/proj/B.h"},
            "/proj/B.h": set(),
        }
        filter_string = "/proj"
        result = apply_filter(edges, filter_string)

        assert "/proj/A.h" in result.included_nodes
        assert "/proj/B.h" in result.included_nodes

    def test_nodes_not_matching_excluded(self):
        """Nodes not matching filter should not be included."""
        edges = {
            "/proj/A.h": {"/external/X.h"},
            "/external/X.h": set(),
        }
        filter_string = "/proj"
        result = apply_filter(edges, filter_string)

        assert "/proj/A.h" in result.included_nodes
        assert "/external/X.h" not in result.included_nodes

    def test_path_through_external_warning(self, filter_test_graph):
        """Warning should be generated for paths through external headers."""
        edges, direct_includes, filter_prefix = filter_test_graph
        all_nodes = set(edges.keys())
        for children in edges.values():
            all_nodes.update(children)

        result = apply_filter(edges, filter_prefix, all_nodes)

        # Should have warning about A -> X -> C path
        assert len(result.warnings) > 0
        # Check warning mentions the external path
        has_external_warning = any("X.h" in w for w in result.warnings)
        assert has_external_warning

    def test_intermediate_nodes_marked(self, filter_test_graph):
        """Intermediate (external) nodes on paths should be marked."""
        edges, direct_includes, filter_prefix = filter_test_graph
        all_nodes = set(edges.keys())
        for children in edges.values():
            all_nodes.update(children)

        result = apply_filter(edges, filter_prefix, all_nodes)

        # X.h is intermediate (on path between included nodes)
        assert "/external/X.h" in result.intermediate_nodes

    def test_no_warnings_for_clean_filter(self):
        """No warnings when all paths stay within filtered nodes."""
        edges = {
            "/proj/A.h": {"/proj/B.h"},
            "/proj/B.h": {"/proj/C.h"},
            "/proj/C.h": set(),
        }
        filter_string = "/proj"
        result = apply_filter(edges, filter_string)

        assert len(result.warnings) == 0
        assert len(result.intermediate_nodes) == 0

    def test_empty_graph(self):
        """Empty graph returns empty result."""
        edges: dict[str, set[str]] = {}
        filter_string = "/proj"
        result = apply_filter(edges, filter_string)

        assert len(result.included_nodes) == 0
        assert len(result.intermediate_nodes) == 0
        assert len(result.warnings) == 0

    def test_all_nodes_excluded(self):
        """When no nodes match filter, result should be empty."""
        edges = {
            "/other/A.h": {"/other/B.h"},
            "/other/B.h": set(),
        }
        filter_string = "/proj"
        result = apply_filter(edges, filter_string)

        assert len(result.included_nodes) == 0

    def test_all_nodes_included(self):
        """When all nodes match filter, all should be included."""
        edges = {
            "/proj/A.h": {"/proj/B.h", "/proj/C.h"},
            "/proj/B.h": {"/proj/D.h"},
            "/proj/C.h": {"/proj/D.h"},
            "/proj/D.h": set(),
        }
        filter_string = "/proj"
        all_nodes = set(edges.keys())
        for children in edges.values():
            all_nodes.update(children)

        result = apply_filter(edges, filter_string, all_nodes)

        assert result.included_nodes == all_nodes
        assert len(result.intermediate_nodes) == 0
        assert len(result.warnings) == 0

    def test_filter_with_explicit_all_nodes(self):
        """Passing explicit all_nodes should work correctly."""
        edges = {
            "/proj/A.h": {"/proj/B.h"},
        }
        all_nodes = {"/proj/A.h", "/proj/B.h", "/proj/C.h"}  # C not in edges
        filter_string = "/proj"

        result = apply_filter(edges, filter_string, all_nodes)

        # All three should be included since they match prefix
        assert "/proj/A.h" in result.included_nodes
        assert "/proj/B.h" in result.included_nodes
        assert "/proj/C.h" in result.included_nodes


class TestFilterResult:
    """Tests for FilterResult dataclass."""

    def test_default_values(self):
        """FilterResult should have sensible defaults."""
        result = FilterResult()

        assert result.included_nodes == set()
        assert result.intermediate_nodes == set()
        assert result.warnings == []

    def test_mutability(self):
        """FilterResult fields should be mutable."""
        result = FilterResult()

        result.included_nodes.add("/proj/A.h")
        result.intermediate_nodes.add("/external/X.h")
        result.warnings.append("Test warning")

        assert "/proj/A.h" in result.included_nodes
        assert "/external/X.h" in result.intermediate_nodes
        assert "Test warning" in result.warnings
