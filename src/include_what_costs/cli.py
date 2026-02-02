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
        "--prmon", type=str, help="Path to prmon binary (enables benchmarking)"
    )
    parser.add_argument(
        "--source-pattern",
        type=str,
        help="Pattern to match source file for compile flags",
    )
    parser.add_argument(
        "--focus",
        type=str,
        action="append",
        help="Focus DOT output on headers matching pattern (can be repeated)",
    )
    parser.add_argument(
        "--focus-depth",
        type=int,
        default=1,
        help="Include N levels of children beyond focused headers (default: 1)",
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
        "--cwd",
        type=Path,
        help="Working directory for resolving relative paths (useful with pixi)",
    )
    parser.add_argument("--config", type=Path, help="Path to YAML config file")

    args = parser.parse_args()

    # Load config file if provided
    if args.config:
        config = load_config(args.config)
        if not args.cwd and "cwd" in config:
            args.cwd = Path(config["cwd"])
        if not args.root and "root" in config:
            args.root = Path(config["root"])
        if not args.compile_commands and "compile-commands" in config:
            args.compile_commands = Path(config["compile-commands"])
        if not args.prmon and "prmon" in config:
            args.prmon = config["prmon"]
        if args.output == Path("results") and "output" in config:
            args.output = Path(config["output"])
        if not args.source_pattern and "source-pattern" in config:
            args.source_pattern = config["source-pattern"]
        if not args.wrapper and "wrapper" in config:
            args.wrapper = config["wrapper"]
        if not args.focus and "focus" in config:
            focus_val = config["focus"]
            # Support both single string and list in config
            if isinstance(focus_val, list):
                args.focus = focus_val
            else:
                args.focus = [focus_val]
        if args.focus_depth == 1 and "focus-depth" in config:
            args.focus_depth = config["focus-depth"]

    # Validate required arguments
    if not args.root:
        parser.error("--root is required")
    if not args.compile_commands:
        parser.error("--compile-commands is required")

    # Resolve all paths to absolute
    # If --cwd is specified, resolve relative paths against it (useful when run via pixi)
    base_dir = args.cwd.resolve() if args.cwd else Path.cwd()

    def resolve_path(p: Path) -> Path:
        if p.is_absolute():
            return p
        return (base_dir / p).resolve()

    args.root = resolve_path(args.root)
    args.compile_commands = resolve_path(args.compile_commands)
    args.output = resolve_path(args.output)
    if args.wrapper and not Path(args.wrapper).is_absolute():
        args.wrapper = str(base_dir / args.wrapper)

    args.output.mkdir(parents=True, exist_ok=True)

    # Build include graph
    print(f"Analyzing {args.root}...")
    if args.wrapper:
        print(f"Using wrapper: {args.wrapper}")
    flags = extract_compile_flags(args.compile_commands, args.source_pattern)
    output = run_gcc_h(args.root, flags, args.cxx_standard, args.wrapper)
    graph = parse_gcc_h_output(output)
    graph.root = str(args.root)  # Store root header path
    print(f"Found {len(graph.all_headers)} unique headers")

    # Generate graph outputs
    generate_json(graph, args.output / "include_graph.json")
    dot_file = args.output / "include_graph.dot"
    generate_dot(graph, dot_file, args.focus, focus_depth=args.focus_depth)
    print("Wrote include_graph.json and include_graph.dot")

    # Generate PNG and SVG if dot is available
    if shutil.which("dot"):
        for fmt in ["png", "svg"]:
            out_file = args.output / f"include_graph.{fmt}"
            subprocess.run(
                ["dot", f"-T{fmt}", str(dot_file), "-o", str(out_file)],
                check=True,
            )
        print("Wrote include_graph.png and include_graph.svg")
    else:
        print("Note: 'dot' not found, skipping PNG/SVG generation")

    # Benchmark if prmon provided
    results = None
    if args.prmon:
        direct_includes = parse_includes(args.root)
        print(f"\nBenchmarking {len(direct_includes)} direct includes...")

        work_dir = Path(tempfile.mkdtemp(prefix="iwc_"))
        results = []

        for i, header in enumerate(direct_includes):
            print(f"[{i + 1}/{len(direct_includes)}] {header}...", end=" ", flush=True)
            r = benchmark_header(header, flags, work_dir, args.prmon, args.wrapper)
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
