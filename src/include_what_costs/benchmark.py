"""Benchmark compile cost of individual headers."""

import json
import shlex
import subprocess
import tempfile
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
    command: str | None = None


def benchmark_header(
    header: str,
    compile_cmd: str,
    work_dir: Path,
    prmon_path: str,
    wrapper: str | None = None,
) -> BenchmarkResult:
    """Benchmark a single header's compile cost.

    Creates a minimal .cpp file that includes the header and measures
    compilation cost using prmon.

    Args:
        header: Header name to benchmark.
        compile_cmd: Base compile command with flags.
        work_dir: Directory to create test files in.
        prmon_path: Path to the prmon binary.
        wrapper: Optional wrapper command (e.g., "./Rec/run").

    Returns:
        BenchmarkResult with RSS, time, and success status.
    """
    safe_name = header.replace("/", "_").replace(".h", "")
    test_dir = work_dir / safe_name
    test_dir.mkdir(parents=True, exist_ok=True)

    test_cpp = test_dir / "test.cpp"
    test_cpp.write_text(f'#include "{header}"\n')

    prmon_json = test_dir / "prmon.json"
    gcc_cmd = f"g++ {compile_cmd} -c {test_cpp} -o {test_dir}/test.o"
    if wrapper:
        full_cmd = f"{wrapper} {gcc_cmd}"
    else:
        full_cmd = gcc_cmd

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
                error=None if result.returncode == 0 else result.stderr[-500:],
                command=full_cmd,
            )

        return BenchmarkResult(
            header=header,
            max_rss_kb=0,
            wall_time_s=0,
            success=False,
            error="No prmon output",
            command=full_cmd,
        )

    except subprocess.TimeoutExpired:
        return BenchmarkResult(
            header=header,
            max_rss_kb=0,
            wall_time_s=300,
            success=False,
            error="Timeout",
            command=full_cmd,
        )
    except Exception as e:
        return BenchmarkResult(
            header=header,
            max_rss_kb=0,
            wall_time_s=0,
            success=False,
            error=str(e),
            command=full_cmd,
        )


def get_preprocessed_size(
    header: str,
    compile_flags: str,
    wrapper: str | None = None,
) -> int:
    """Get size of preprocessed output for a header via gcc -E.

    Creates a minimal .cpp file that includes the header and measures
    the size of the preprocessed output.

    Args:
        header: Header name to measure.
        compile_flags: Base compile command with flags.
        wrapper: Optional wrapper command (e.g., "./Rec/run").

    Returns:
        Size of preprocessed output in bytes, or 0 on error.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cpp", delete=False
    ) as f:
        f.write(f'#include "{header}"\n')
        test_cpp = f.name

    try:
        gcc_cmd = f"g++ -E {compile_flags} {test_cpp}"
        if wrapper:
            cmd = f"{wrapper} bash -c {shlex.quote(gcc_cmd)}"
        else:
            cmd = gcc_cmd

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60
        )
        return len(result.stdout) if result.returncode == 0 else 0
    except (subprocess.TimeoutExpired, Exception):
        return 0
    finally:
        Path(test_cpp).unlink(missing_ok=True)
