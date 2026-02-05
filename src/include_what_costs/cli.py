"""CLI for include-what-costs."""

import argparse
import json
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .benchmark import benchmark_header, get_preprocessed_size
from .graph import (
    extract_compile_flags,
    parse_gcc_h_output,
    run_gcc_h,
    supplement_edges_from_parsing,
)
from .parse_header import parse_includes
from .visualize import generate_csv, generate_html, generate_json, generate_summary


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        Dictionary of configuration values.
    """
    try:
        import yaml

        with open(config_path) as f:
            return yaml.safe_load(f)
    except ImportError as err:
        raise ImportError("PyYAML required for config files: pip install pyyaml") from err


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add common arguments shared between subcommands."""
    parser.add_argument("--root", type=Path, help="Root header file to analyze")
    parser.add_argument("--compile-commands", type=Path, help="Path to compile_commands.json")
    parser.add_argument(
        "--prefix",
        type=str,
        action="append",
        help="Only show headers under this path prefix (can be repeated)",
    )
    parser.add_argument(
        "--wrapper",
        type=str,
        help="Wrapper command for gcc (e.g., ./Rec/run)",
    )
    parser.add_argument("--config", type=Path, help="Path to YAML config file")


def resolve_common_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Resolve common arguments: load config, validate, and resolve paths."""
    # Load config file if provided
    if args.config:
        config = load_config(args.config)
        if not args.root and "root" in config:
            args.root = Path(config["root"])
        if not args.compile_commands and "compile-commands" in config:
            args.compile_commands = Path(config["compile-commands"])
        if not args.wrapper and "wrapper" in config:
            args.wrapper = config["wrapper"]
        if not args.prefix and "prefix" in config:
            val = config["prefix"]
            args.prefix = val if isinstance(val, list) else [val]

    # Validate required arguments
    if not args.root:
        parser.error("--root is required")
    if not args.compile_commands:
        parser.error("--compile-commands is required")

    # Resolve all paths to absolute
    args.root = args.root.resolve()
    args.compile_commands = args.compile_commands.resolve()
    if args.wrapper:
        wrapper_path = Path(args.wrapper)
        if not wrapper_path.is_absolute():
            args.wrapper = str(Path.cwd() / wrapper_path)
    if args.prefix:
        args.prefix = [str(Path(p).resolve()) for p in args.prefix]


def build_graph(args: argparse.Namespace):
    """Build the include graph from args.

    Returns:
        Tuple of (graph, flags) where graph is the IncludeGraph and flags are the compile flags.
    """
    print(f"Analyzing {args.root}...")
    if args.wrapper:
        print(f"Using wrapper: {args.wrapper}")
    flags = extract_compile_flags(args.compile_commands, root_header=args.root)
    output = run_gcc_h(args.root, flags, args.wrapper)
    print(f"gcc -H output length: {len(output)} chars")
    graph = parse_gcc_h_output(output)
    graph.root = str(args.root)  # Store root header path
    # Add root to graph with edges to its direct includes
    graph.all_headers.add(graph.root)
    graph.edges[graph.root] = graph.direct_includes.copy()
    print(f"Found {len(graph.all_headers)} unique headers")

    if len(graph.all_headers) == 0:
        import shlex

        print("ERROR: No headers found. Check that the root header exists and compiles.")
        print("Try running the gcc command manually to debug:")
        gcc_cmd = f"g++ -H -E {flags} {shlex.quote(str(args.root))}"
        if args.wrapper:
            print(f"  {args.wrapper} bash -c {shlex.quote(gcc_cmd)}")
        else:
            print(f"  {gcc_cmd}")
        return None, flags

    # Supplement edges by parsing headers directly (gcc -H misses some)
    added = supplement_edges_from_parsing(graph)
    if added:
        print(f"Added {added} edges from direct header parsing")

    return graph, flags


def cmd_analyze(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Run the analyze subcommand (original behavior)."""
    # Load config extras specific to analyze
    if args.config:
        config = load_config(args.config)
        if args.output == Path("results") and "output" in config:
            args.output = Path(config["output"])
        if args.benchmark is None and "benchmark" in config:
            val = config["benchmark"]
            if val is True or val == "all":
                args.benchmark = -1  # all headers
            elif isinstance(val, int):
                args.benchmark = val

    resolve_common_args(args, parser)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)

    # Build include graph
    graph, flags = build_graph(args)
    if graph is None:
        return

    # Parse direct includes from root header file (more accurate than gcc -H depth tracking)
    direct_includes = parse_includes(args.root)

    # Generate JSON output (HTML generated after benchmarking to include results)
    generate_json(graph, args.output / "include_graph.json")
    print("Wrote include_graph.json")

    # Benchmark headers
    results = None
    if args.benchmark is not None:
        # Build candidate list
        candidates = list(graph.all_headers)
        if args.prefix:
            candidates = [h for h in candidates if any(h.startswith(p) for p in args.prefix)]

        # Always include root header to show total compilation cost
        root_header = str(args.root)

        if args.benchmark == -1 or args.benchmark >= len(candidates):
            # Benchmark all headers, sorted by depth (lower depth = likely more expensive)
            # Root header first, then by ascending depth
            headers_to_benchmark = sorted(candidates, key=lambda h: graph.header_depths.get(h, 999))
            headers_to_benchmark.insert(0, root_header)
            if args.benchmark == -1:
                print(f"\nBenchmarking all {len(headers_to_benchmark)} headers")
            else:
                print(
                    f"\nBenchmarking all {len(headers_to_benchmark)} headers (N={args.benchmark} >= {len(candidates)} candidates)"
                )
        else:
            # --benchmark=N: select top N by (depth, preprocessed_size)
            print(f"\nSelecting top {args.benchmark} headers from {len(candidates)} candidates...")

            if not candidates:
                print("No candidates to benchmark after filtering.")
                headers_to_benchmark = [root_header]
            else:
                # Compute (depth, preprocessed_size) for each candidate in parallel
                header_metrics: list[tuple[str, int, int]] = []
                num_workers = max(1, min(os.cpu_count() or 4, len(candidates)))
                print(f"Measuring preprocessed sizes with {num_workers} workers...")

                with ProcessPoolExecutor(max_workers=num_workers) as executor:
                    # Submit all tasks
                    future_to_header = {
                        executor.submit(get_preprocessed_size, header, flags, args.wrapper): header
                        for header in candidates
                    }

                    # Collect results as they complete
                    for i, future in enumerate(as_completed(future_to_header)):
                        header = future_to_header[future]
                        depth = graph.header_depths.get(header, 999)
                        try:
                            size = future.result()
                        except Exception:
                            size = 0
                        header_metrics.append((header, depth, size))
                        print(f"[{i + 1}/{len(candidates)}] depth={depth}, size={size:,}: {header}")

                # Sort by (depth ascending, size descending)
                header_metrics.sort(key=lambda x: (x[1], -x[2]))

                # Take top N (already sorted by depth asc, size desc)
                headers_to_benchmark = [h for h, _, _ in header_metrics[: args.benchmark]]
                print(f"\nSelected {len(headers_to_benchmark)} headers for benchmarking:")
                for h, d, s in header_metrics[: args.benchmark]:
                    print(f"  depth={d}, size={s:,}: {h}")

                # Add root header at front (likely most expensive)
                headers_to_benchmark.insert(0, root_header)

        if not headers_to_benchmark:
            print("\nNo headers to benchmark.")
            results = []
        else:
            # Calculate max parallel workers: min(cpu_count, total_memory_gb / 3)
            cpu_count = os.cpu_count() or 4
            try:
                mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                mem_gb = mem_bytes / (1024**3)
                mem_workers = int(mem_gb / 3)
            except (ValueError, OSError):
                mem_workers = cpu_count  # Fallback if sysconf unavailable
            num_workers = max(1, min(cpu_count, mem_workers, len(headers_to_benchmark)))

            print(
                f"\nBenchmarking {len(headers_to_benchmark)} headers with {num_workers} workers..."
            )

            work_dir = Path(tempfile.mkdtemp(prefix="iwc_"))
            results = []

            with ProcessPoolExecutor(max_workers=num_workers) as executor:
                future_to_header = {
                    executor.submit(
                        benchmark_header, header, flags, work_dir, "prmon", args.wrapper
                    ): header
                    for header in headers_to_benchmark
                }

                for i, future in enumerate(as_completed(future_to_header)):
                    header = future_to_header[future]
                    try:
                        r = future.result()
                    except Exception as e:
                        print(f"[{i + 1}/{len(headers_to_benchmark)}] {header}... ERROR: {e}")
                        continue
                    results.append(r.__dict__)

                    if r.success:
                        print(
                            f"[{i + 1}/{len(headers_to_benchmark)}] {header}... RSS={r.max_rss_kb / 1024:.0f}MB, time={r.wall_time_s:.1f}s"
                        )
                    else:
                        print(
                            f"[{i + 1}/{len(headers_to_benchmark)}] {header}... FAILED: {r.error}"
                        )
                        print(f"    Command: {r.command}")

            # Write benchmark outputs
            with open(args.output / "header_costs.json", "w") as f:
                json.dump(results, f, indent=2)

            generate_csv(results, args.output / "header_costs.csv")
            print("\nWrote header_costs.json and header_costs.csv")

            # Print summary
            ok = [r for r in results if r["success"]]
            if ok:
                print("\n=== TOP 10 BY RSS ===")
                for r in sorted(ok, key=lambda x: -x["max_rss_kb"])[:10]:
                    print(f"  {r['max_rss_kb'] / 1024:6.0f} MB  {r['header']}")

                print("\n=== TOP 10 BY TIME ===")
                for r in sorted(ok, key=lambda x: -x["wall_time_s"])[:10]:
                    print(f"  {r['wall_time_s']:6.1f} s   {r['header']}")

    # Generate HTML with benchmark data (if available)
    generate_html(
        graph,
        args.output / "include_graph.html",
        args.prefix,
        direct_includes,
        benchmark_results=results,
    )
    print("Wrote include_graph.html")

    # Generate summary
    generate_summary(graph, results, args.output / "summary.txt")
    print("\nWrote summary.txt")
    print(f"\nAll outputs written to {args.output}/")


def cmd_consolidate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Run the consolidate subcommand."""
    from .consolidate import run_consolidate

    resolve_common_args(args, parser)

    if not args.prefix:
        parser.error("--prefix is required for consolidate (to identify your code)")

    # Build include graph
    graph, flags = build_graph(args)
    if graph is None:
        return

    # Run consolidation analysis
    run_consolidate(
        graph=graph,
        pattern=args.pattern,
        prefixes=args.prefix,
        compile_flags=flags,
        wrapper=args.wrapper,
        output_path=args.output,
    )


def find_matching_header(all_headers: set[str], pattern: str) -> str | None:
    """Find header matching pattern (substring). Error if ambiguous."""
    matches = [h for h in all_headers if pattern in h]
    if len(matches) == 0:
        print(f"Error: No header matching '{pattern}'")
        return None
    if len(matches) > 1:
        print(f"Error: Ambiguous pattern '{pattern}' matches:")
        for m in sorted(matches)[:10]:
            print(f"  {m}")
        if len(matches) > 10:
            print(f"  ... and {len(matches) - 10} more")
        return None
    return matches[0]


def find_include_paths(
    edges: dict[str, set[str]], start: str, end: str, max_paths: int
) -> tuple[list[list[str]], int]:
    """Find shortest include paths and total count.

    Args:
        edges: Graph adjacency list (parent -> children).
        start: Starting header.
        end: Target header.
        max_paths: Maximum number of paths to return.

    Returns:
        Tuple of (list_of_paths, total_count_of_shortest_paths).
        If no path exists, returns ([], 0).
    """
    from collections import deque

    # First pass: BFS to find shortest distances
    dist: dict[str, int] = {start: 0}
    queue = deque([start])

    while queue:
        current = queue.popleft()
        for neighbor in edges.get(current, []):
            if neighbor not in dist:
                dist[neighbor] = dist[current] + 1
                queue.append(neighbor)

    # No path exists
    if end not in dist:
        return [], 0

    # Second pass: count shortest paths using DP
    path_count: dict[str, int] = {start: 1}
    for d in range(1, dist[end] + 1):
        nodes_at_d = [n for n, nd in dist.items() if nd == d]
        for node in nodes_at_d:
            count = 0
            for pred, children in edges.items():
                if node in children and dist.get(pred) == d - 1:
                    count += path_count.get(pred, 0)
            path_count[node] = count

    total_count = path_count.get(end, 0)

    # Third pass: collect up to max_paths using DFS
    paths: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        if len(paths) >= max_paths:
            return
        if node == end:
            paths.append(path.copy())
            return
        # Only follow edges to nodes at distance + 1 (shortest path edges)
        current_dist = dist[node]
        for neighbor in edges.get(node, []):
            if dist.get(neighbor) == current_dist + 1:
                path.append(neighbor)
                dfs(neighbor, path)
                path.pop()
                if len(paths) >= max_paths:
                    return

    dfs(start, [start])

    return paths, total_count


def print_include_chain(path: list[str], prefix: list[str] | None) -> None:
    """Print the include chain with indentation."""
    for i, header in enumerate(path):
        # Shorten path if prefix provided
        display = header
        if prefix:
            for p in prefix:
                if header.startswith(p):
                    display = header[len(p) :].lstrip("/")
                    break
        indent = "  " * i
        arrow = "-> " if i > 0 else ""
        print(f"{indent}{arrow}{display}")


def cmd_trace(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Find and display the include path between two headers."""
    resolve_common_args(args, parser)

    # Build include graph
    graph, _ = build_graph(args)
    if graph is None:
        return

    # Find matching headers (--from defaults to root)
    if args.from_header:
        from_header = find_matching_header(graph.all_headers, args.from_header)
    else:
        from_header = graph.root
    to_header = find_matching_header(graph.all_headers, args.to_header)

    if not from_header or not to_header:
        return

    # Find shortest paths
    paths, total_count = find_include_paths(graph.edges, from_header, to_header, args.max_paths)

    if not paths:
        print(f"No path found from {from_header} to {to_header}")
        return

    path_len = len(paths[0])
    not_shown = total_count - len(paths)
    extra_msg = f", {not_shown} more not shown" if not_shown > 0 else ""

    print(f"\n{total_count} shortest path(s) of length {path_len}{extra_msg}:\n")

    for i, path in enumerate(paths):
        if i > 0:
            print()  # Blank line between paths
        print(f"Path {i + 1}:")
        print_include_chain(path, args.prefix)


def main() -> None:
    """Main entry point for include-what-costs CLI."""
    parser = argparse.ArgumentParser(
        description="Analyze C++ header dependencies and compile costs"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Analyze subcommand (original behavior)
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze header dependencies and optionally benchmark compile costs",
    )
    add_common_args(analyze_parser)
    analyze_parser.add_argument(
        "--output",
        type=Path,
        default=Path("results"),
        help="Output directory (default: results)",
    )
    analyze_parser.add_argument(
        "--benchmark",
        nargs="?",
        const=-1,  # --benchmark without value means all
        type=int,
        metavar="N",
        help="Benchmark headers. Without N: all headers. With N: top N by (depth, preprocessed size)",
    )

    # Consolidate subcommand (new)
    consolidate_parser = subparsers.add_parser(
        "consolidate",
        help="Analyze cost of consolidating external dependencies",
    )
    add_common_args(consolidate_parser)
    consolidate_parser.add_argument(
        "--pattern",
        type=str,
        required=True,
        help="Substring pattern to match external headers (e.g., 'DD4hep')",
    )
    consolidate_parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path",
    )

    # Trace subcommand (find include path between two headers)
    trace_parser = subparsers.add_parser(
        "trace",
        help="Find the include path between two headers",
    )
    add_common_args(trace_parser)
    trace_parser.add_argument(
        "--from",
        dest="from_header",
        help="Source header (substring match, defaults to --root)",
    )
    trace_parser.add_argument(
        "--to",
        dest="to_header",
        required=True,
        help="Target header (substring match)",
    )
    trace_parser.add_argument(
        "-n",
        "--max-paths",
        type=int,
        default=10,
        help="Maximum number of paths to show (default: 10)",
    )

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args, analyze_parser)
    elif args.command == "consolidate":
        cmd_consolidate(args, consolidate_parser)
    elif args.command == "trace":
        cmd_trace(args, trace_parser)
    else:
        # No subcommand provided - show help
        parser.print_help()


if __name__ == "__main__":
    main()
