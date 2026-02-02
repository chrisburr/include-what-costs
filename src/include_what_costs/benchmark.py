"""Benchmark compile cost of individual headers."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BenchmarkResult:
    """Result of benchmarking a single header's compile cost."""

    header: str
    max_rss_kb: int
    wall_time_s: float
    success: bool
    error: str | None = None


def benchmark_header(
    header: str, compile_cmd: str, work_dir: Path, prmon_path: str
) -> BenchmarkResult:
    """Benchmark a single header's compile cost.

    Creates a minimal .cpp file that includes the header and measures
    compilation cost using prmon.

    Args:
        header: Header name to benchmark.
        compile_cmd: Base compile command with flags.
        work_dir: Directory to create test files in.
        prmon_path: Path to the prmon binary.

    Returns:
        BenchmarkResult with RSS, time, and success status.
    """
    safe_name = header.replace("/", "_").replace(".h", "")
    test_dir = work_dir / safe_name
    test_dir.mkdir(parents=True, exist_ok=True)

    test_cpp = test_dir / "test.cpp"
    test_cpp.write_text(f'#include "{header}"\n')

    prmon_json = test_dir / "prmon.json"
    full_cmd = f"g++ {compile_cmd} -c {test_cpp} -o {test_dir}/test.o"

    cmd = [
        prmon_path,
        "--interval",
        "0.1",
        "--json-summary",
        str(prmon_json),
        "--",
        "bash",
        "-c",
        full_cmd,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if prmon_json.exists():
            with open(prmon_json) as f:
                metrics = json.load(f)

            return BenchmarkResult(
                header=header,
                max_rss_kb=metrics["Max"]["rss"],
                wall_time_s=metrics["Max"]["wtime"],
                success=result.returncode == 0,
                error=None if result.returncode == 0 else result.stderr[:200],
            )

        return BenchmarkResult(
            header=header,
            max_rss_kb=0,
            wall_time_s=0,
            success=False,
            error="No prmon output",
        )

    except subprocess.TimeoutExpired:
        return BenchmarkResult(
            header=header,
            max_rss_kb=0,
            wall_time_s=300,
            success=False,
            error="Timeout",
        )
    except Exception as e:
        return BenchmarkResult(
            header=header,
            max_rss_kb=0,
            wall_time_s=0,
            success=False,
            error=str(e),
        )
