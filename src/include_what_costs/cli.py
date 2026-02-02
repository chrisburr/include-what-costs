"""CLI for include-what-costs."""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .benchmark import benchmark_header
from .graph import extract_compile_flags, parse_gcc_h_output, run_gcc_h
from .parse_header import parse_includes
from .visualize import generate_csv, generate_dot, generate_json, generate_summary


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
        "--cxx-standard", default="c++20", help="C++ standard (default: c++20)"
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
    output = run_gcc_h(args.root, flags, args.cxx_standard, args.wrapper)
    print(f"gcc -H output length: {len(output)} chars")
    graph = parse_gcc_h_output(output)
    graph.root = str(args.root)  # Store root header path
    print(f"Found {len(graph.all_headers)} unique headers")

    # Parse direct includes from root header file (more accurate than gcc -H depth tracking)
    direct_includes = parse_includes(args.root)

    # Generate graph outputs
    generate_json(graph, args.output / "include_graph.json")
    dot_file = args.output / "include_graph.dot"
    generate_dot(graph, dot_file, args.prefix, direct_includes)
    print("Wrote include_graph.json and include_graph.dot")

    # Generate PNG and SVG using twopi (radial layout)
    if shutil.which("twopi"):
        for fmt in ["png", "svg"]:
            out_file = args.output / f"include_graph.{fmt}"
            subprocess.run(
                ["twopi", f"-T{fmt}", str(dot_file), "-o", str(out_file)],
                check=True,
            )
        print("Wrote include_graph.png and include_graph.svg")
    else:
        print("Note: 'twopi' not found, skipping PNG/SVG generation")

    # Benchmark headers
    results = None
    if not args.no_benchmark:
        direct_includes = parse_includes(args.root)
        print(f"\nBenchmarking {len(direct_includes)} direct includes...")

        work_dir = Path(tempfile.mkdtemp(prefix="iwc_"))
        results = []

        for i, header in enumerate(direct_includes):
            print(f"[{i + 1}/{len(direct_includes)}] {header}...", end=" ", flush=True)
            r = benchmark_header(header, flags, work_dir, "prmon", args.wrapper)
            results.append(r.__dict__)

            if r.success:
                print(f"RSS={r.max_rss_kb / 1024:.0f}MB, time={r.wall_time_s:.1f}s")
            else:
                print("FAILED")

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

    # Generate summary
    generate_summary(graph, results, args.output / "summary.txt")
    print(f"\nWrote summary.txt")
    print(f"\nAll outputs written to {args.output}/")


if __name__ == "__main__":
    main()
