"""Tests for consolidate module."""

import pytest

from include_what_costs.consolidate import (
    ExternalHeaderInfo,
    find_external_headers_with_includers,
    generate_synthetic_header,
)
from include_what_costs.graph import IncludeGraph


class TestFindExternalHeadersWithIncluders:
    """Tests for find_external_headers_with_includers function."""

    def test_finds_matching_headers(self):
        """Test that headers matching pattern are found."""
        graph = IncludeGraph()
        graph.edges["/my/code/a.h"] = {"/external/DD4hep/Handle.h"}
        graph.edges["/my/code/b.h"] = {"/external/DD4hep/Handle.h"}
        graph.all_headers = {
            "/my/code/a.h",
            "/my/code/b.h",
            "/external/DD4hep/Handle.h",
        }

        results = find_external_headers_with_includers(
            graph, pattern="DD4hep", prefixes=["/my/code"]
        )

        assert len(results) == 1
        assert results[0].header == "/external/DD4hep/Handle.h"
        assert results[0].direct_includer_count == 2
        assert set(results[0].direct_includers) == {"/my/code/a.h", "/my/code/b.h"}

    def test_excludes_headers_not_included_by_prefix(self):
        """Test that external headers not included by prefix code are excluded."""
        graph = IncludeGraph()
        # DD4hep header only included by non-prefix code
        graph.edges["/other/code.h"] = {"/external/DD4hep/Handle.h"}
        graph.all_headers = {"/other/code.h", "/external/DD4hep/Handle.h"}

        results = find_external_headers_with_includers(
            graph, pattern="DD4hep", prefixes=["/my/code"]
        )

        assert len(results) == 0

    def test_sorted_by_includer_count(self):
        """Test that results are sorted by includer count descending."""
        graph = IncludeGraph()
        graph.edges["/my/a.h"] = {"/ext/low.h"}
        graph.edges["/my/b.h"] = {"/ext/high.h"}
        graph.edges["/my/c.h"] = {"/ext/high.h"}
        graph.all_headers = {"/my/a.h", "/my/b.h", "/my/c.h", "/ext/low.h", "/ext/high.h"}

        results = find_external_headers_with_includers(
            graph, pattern="ext", prefixes=["/my"]
        )

        assert len(results) == 2
        assert results[0].header == "/ext/high.h"  # 2 includers
        assert results[1].header == "/ext/low.h"   # 1 includer

    def test_no_matches(self):
        """Test empty result when no headers match pattern."""
        graph = IncludeGraph()
        graph.edges["/my/a.h"] = {"/other/lib.h"}
        graph.all_headers = {"/my/a.h", "/other/lib.h"}

        results = find_external_headers_with_includers(
            graph, pattern="DD4hep", prefixes=["/my"]
        )

        assert len(results) == 0


class TestGenerateSyntheticHeader:
    """Tests for generate_synthetic_header function."""

    def test_generates_includes(self):
        """Test that includes are generated for all headers."""
        headers = ["/path/to/a.h", "/path/to/b.h"]

        content = generate_synthetic_header(headers)

        assert '#include "/path/to/a.h"' in content
        assert '#include "/path/to/b.h"' in content

    def test_sorted_includes(self):
        """Test that includes are sorted alphabetically."""
        headers = ["/z/header.h", "/a/header.h"]

        content = generate_synthetic_header(headers)

        lines = content.strip().split("\n")
        include_lines = [l for l in lines if l.startswith("#include")]
        assert include_lines[0] == '#include "/a/header.h"'
        assert include_lines[1] == '#include "/z/header.h"'

    def test_has_pragma_once(self):
        """Test that generated header has #pragma once."""
        content = generate_synthetic_header(["/a.h"])

        assert "#pragma once" in content

    def test_empty_list(self):
        """Test generating header with no includes."""
        content = generate_synthetic_header([])

        assert "#pragma once" in content
        assert "#include" not in content
