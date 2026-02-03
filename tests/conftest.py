"""Pytest fixtures for layout module tests."""

import pytest


@pytest.fixture
def simple_chain() -> tuple[dict[str, set[str]], set[str]]:
    """Simple chain: A -> B -> C (depths 1, 2, 3)."""
    edges = {
        "A": {"B"},
        "B": {"C"},
        "C": set(),
    }
    direct_includes = {"A"}
    return edges, direct_includes


@pytest.fixture
def diamond_graph() -> tuple[dict[str, set[str]], set[str]]:
    """Diamond: A -> B, A -> C, B -> D, C -> D (D at depth 3)."""
    edges = {
        "A": {"B", "C"},
        "B": {"D"},
        "C": {"D"},
        "D": set(),
    }
    direct_includes = {"A"}
    return edges, direct_includes


@pytest.fixture
def multiple_roots() -> tuple[dict[str, set[str]], set[str]]:
    """Multiple depth-1 nodes: A, B both direct includes."""
    edges = {
        "A": {"C"},
        "B": {"C"},
        "C": {"D"},
        "D": set(),
    }
    direct_includes = {"A", "B"}
    return edges, direct_includes


@pytest.fixture
def back_edge_graph() -> tuple[dict[str, set[str]], set[str]]:
    """Graph with back edge: A -> B -> C -> A (cycle)."""
    edges = {
        "A": {"B"},
        "B": {"C"},
        "C": {"A"},  # Back edge
    }
    direct_includes = {"A"}
    return edges, direct_includes


@pytest.fixture
def same_level_graph() -> tuple[dict[str, set[str]], set[str]]:
    """Graph with same-level edge: A -> B, A -> C, B -> C."""
    edges = {
        "A": {"B", "C"},
        "B": {"C"},  # Same-level edge (both B and C at depth 2)
        "C": set(),
    }
    direct_includes = {"A"}
    return edges, direct_includes


@pytest.fixture
def forward_skip_graph() -> tuple[dict[str, set[str]], set[str]]:
    """Graph with forward skip edge: A -> B -> C, A -> C (skip from A to C)."""
    edges = {
        "A": {"B", "C"},  # A->C is forward skip when B->C exists
        "B": {"C"},
        "C": set(),
    }
    direct_includes = {"A"}
    return edges, direct_includes


@pytest.fixture
def complex_graph() -> tuple[dict[str, set[str]], set[str]]:
    """Complex graph with multiple depths and edge types."""
    edges = {
        "/proj/A.h": {"/proj/B.h", "/proj/C.h"},
        "/proj/B.h": {"/proj/D.h", "/proj/E.h"},
        "/proj/C.h": {"/proj/E.h", "/proj/F.h"},
        "/proj/D.h": {"/proj/G.h"},
        "/proj/E.h": {"/proj/G.h"},
        "/proj/F.h": {"/proj/G.h", "/proj/B.h"},  # Back edge to B
        "/proj/G.h": set(),
    }
    direct_includes = {"/proj/A.h"}
    return edges, direct_includes


@pytest.fixture
def filter_test_graph() -> tuple[dict[str, set[str]], set[str], str]:
    """Graph for filter testing with mixed paths."""
    edges = {
        "/proj/A.h": {"/proj/B.h", "/external/X.h"},
        "/proj/B.h": {"/proj/C.h"},
        "/external/X.h": {"/proj/C.h"},  # Path through external
        "/proj/C.h": set(),
    }
    direct_includes = {"/proj/A.h"}
    filter_prefix = "/proj"
    return edges, direct_includes, filter_prefix
