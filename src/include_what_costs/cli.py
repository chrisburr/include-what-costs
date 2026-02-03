"""CLI for include-what-costs."""

import argparse
import json
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .benchmark import benchmark_header, get_preprocessed_size
from .graph import extract_compile_flags, parse_gcc_h_output, run_gcc_h
from .parse_header import parse_includes
from .visualize import generate_csv, generate_dot, generate_html, generate_json, generate_summary


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
    except ImportError:
        raise ImportError("PyYAML required for config files: pip install pyyaml")


def main() -> None:
    """Main entry point for include-what-costs CLI."""
    parser = argparse.ArgumentParser(
        description="Analyze C++ header dependencies and compile costs"
    )
    parser.add_argument(
        "--root", type=Path, help="Root header file to analyze"
    )
    parser.add_argument(
        "--compile-commands", type=Path, help="Path to compile_commands.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results"),
        help="Output directory (default: results)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        help="Only show headers under this path prefix in the graph",
    )
    parser.add_argument(
        "--wrapper",
        type=str,
        help="Wrapper command for gcc (e.g., ./Rec/run)",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="Skip header cost benchmarking",
    )
    parser.add_argument(
        "--benchmark-limit",
        type=int,
        metavar="N",
        help="Benchmark only the N largest headers (by depth, then preprocessed size)",
    )
    parser.add_argument("--config", type=Path, help="Path to YAML config file")

    args = parser.parse_args()

    # Load config file if provided
    if args.config:
        config = load_config(args.config)
        if not args.root and "root" in config:
            args.root = Path(config["root"])
        if not args.compile_commands and "compile-commands" in config:
            args.compile_commands = Path(config["compile-commands"])
        if args.output == Path("results") and "output" in config:
            args.output = Path(config["output"])
        if not args.wrapper and "wrapper" in config:
            args.wrapper = config["wrapper"]
        if not args.prefix and "prefix" in config:
            args.prefix = config["prefix"]
        if args.benchmark_limit is None and "benchmark-limit" in config:
            args.benchmark_limit = config["benchmark-limit"]

    # Validate required arguments
    if not args.root:
        parser.error("--root is required")
    if not args.compile_commands:
        parser.error("--compile-commands is required")

    # Resolve all paths to absolute
    args.root = args.root.resolve()
    args.compile_commands = args.compile_commands.resolve()
    args.output = args.output.resolve()
    if args.wrapper:
        wrapper_path = Path(args.wrapper)
        if not wrapper_path.is_absolute():
            args.wrapper = str(Path.cwd() / wrapper_path)
    if args.prefix:
        args.prefix = str(Path(args.prefix).resolve())

    args.output.mkdir(parents=True, exist_ok=True)

    # Build include graph
    print(f"Analyzing {args.root}...")
    if args.wrapper:
        print(f"Using wrapper: {args.wrapper}")
    flags = extract_compile_flags(args.compile_commands, root_header=args.root)
    print(f"Compile flags (first 500 chars): {flags[:500]}...")
    output = run_gcc_h(args.root, flags, args.wrapper)
    print(f"gcc -H output length: {len(output)} chars")
    graph = parse_gcc_h_output(output)
    graph.root = str(args.root)  # Store root header path
    print(f"Found {len(graph.all_headers)} unique headers")

    # Parse direct includes from root header file (more accurate than gcc -H depth tracking)
    direct_includes = parse_includes(args.root)

    # Generate JSON output (HTML generated after benchmarking to include results)
    generate_json(graph, args.output / "include_graph.json")
    print("Wrote include_graph.json")

    # Benchmark headers
    results = None
    if not args.no_benchmark:
        # Determine which headers to benchmark
        if args.benchmark_limit is not None:
            # Select top N headers from all candidates
            candidates = list(graph.all_headers)
            if args.prefix:
                candidates = [h for h in candidates if h.startswith(args.prefix)]

            print(f"\nSelecting top {args.benchmark_limit} headers from {len(candidates)} candidates...")

            # Compute (depth, preprocessed_size) for each candidate in parallel
            header_metrics: list[tuple[str, int, int]] = []
            num_workers = min(os.cpu_count() or 4, len(candidates))
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

            # Take top N
            headers_to_benchmark = [h for h, _, _ in header_metrics[: args.benchmark_limit]]
            print(f"\nSelected {len(headers_to_benchmark)} headers for benchmarking:")
            for h, d, s in header_metrics[: args.benchmark_limit]:
                print(f"  depth={d}, size={s:,}: {h}")
        else:
            # Default behavior: benchmark direct includes only
            headers_to_benchmark = list(parse_includes(args.root))

        # Calculate max parallel workers: min(cpu_count, total_memory_gb / 3)
        cpu_count = os.cpu_count() or 4
        try:
            mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            mem_gb = mem_bytes / (1024**3)
            mem_workers = int(mem_gb / 3)
        except (ValueError, OSError):
            mem_workers = cpu_count  # Fallback if sysconf unavailable
        num_workers = max(1, min(cpu_count, mem_workers, len(headers_to_benchmark)))

        print(f"\nBenchmarking {len(headers_to_benchmark)} headers with {num_workers} workers...")

        work_dir = Path(tempfile.mkdtemp(prefix="iwc_"))
        results = []

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            future_to_header = {
                executor.submit(benchmark_header, header, flags, work_dir, "prmon", args.wrapper): header
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
                    print(f"[{i + 1}/{len(headers_to_benchmark)}] {header}... RSS={r.max_rss_kb / 1024:.0f}MB, time={r.wall_time_s:.1f}s")
                else:
                    print(f"[{i + 1}/{len(headers_to_benchmark)}] {header}... FAILED: {r.error}")
                    print(f"    Command: {r.command}")

        # Write benchmark outputs
        with open(args.output / "header_costs.json", "w") as f:
            json.dump(results, f, indent=2)

        generate_csv(results, args.output / "header_costs.csv")
        print(f"\nWrote header_costs.json and header_costs.csv")

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
    print(f"\nWrote summary.txt")
    print(f"\nAll outputs written to {args.output}/")


if __name__ == "__main__":
    main()
