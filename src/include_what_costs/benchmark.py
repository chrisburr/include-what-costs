"""Benchmark compile cost of individual headers."""

import json
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


def _parse_time_v_output(stderr: str) -> tuple[int, float, float]:
    """Parse /usr/bin/time -v output from stderr.

    Args:
        stderr: Combined stderr containing time -v output.

    Returns:
        Tuple of (max_rss_kb, cpu_seconds, elapsed_seconds).
        cpu_seconds = user_time + system_time (more stable than wall time).
    """
    rss_kb = 0
    user_s = 0.0
    system_s = 0.0
    elapsed_s = 0.0

    for line in stderr.splitlines():
        line = line.strip()
        # Maximum resident set size (kbytes): 123456
        if "Maximum resident set size" in line:
            match = re.search(r"(\d+)", line)
            if match:
                rss_kb = int(match.group(1))
        # User time (seconds): 1.23
        elif "User time (seconds)" in line:
            match = re.search(r"([\d.]+)", line)
            if match:
                user_s = float(match.group(1))
        # System time (seconds): 0.45
        elif "System time (seconds)" in line:
            match = re.search(r"([\d.]+)", line)
            if match:
                system_s = float(match.group(1))
        # Elapsed (wall clock) time (h:mm:ss or m:ss): 0:01.68
        elif "Elapsed (wall clock) time" in line:
            match = re.search(r"(\d+):(\d+)[.:](\d+)", line)
            if match:
                minutes = int(match.group(1))
                seconds = int(match.group(2))
                fraction = int(match.group(3))
                # Handle both m:ss.ff and h:mm:ss formats
                elapsed_s = minutes * 60 + seconds + fraction / 100

    cpu_s = user_s + system_s
    return rss_kb, cpu_s, elapsed_s


@dataclass
class BenchmarkResult:
    """Result of benchmarking a single header's compile cost."""

    header: str
    max_rss_kb: int
    wall_time_s: float
    success: bool
    error: str | None = None
    command: str | None = None
    # Additional metrics from both tools for comparison
    prmon_rss_kb: int = 0
    prmon_wtime_s: float = 0.0
    time_rss_kb: int = 0
    time_cpu_s: float = 0.0  # user + system (more stable than wall time)


def benchmark_header(
    header: str,
    compile_cmd: str,
    work_dir: Path,
    prmon_path: str,
    wrapper: str | None = None,
) -> BenchmarkResult:
    """Benchmark a single header's compile cost.

    Creates a minimal .cpp file that includes the header and measures
    compilation cost using both prmon and /usr/bin/time -v for reliability.
    The max RSS is taken as the maximum of both tools' measurements.

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

    # Wrap with /usr/bin/time -v, then monitor with prmon
    # This gives us RSS measurements from both tools
    cmd = [
        prmon_path,
        "--interval",
        "0.1",
        "--json-summary",
        str(prmon_json),
        "--",
        "/usr/bin/time",
        "-v",
        "bash",
        "-c",
        full_cmd,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        # Parse /usr/bin/time -v output from stderr
        time_rss_kb, time_cpu_s, time_elapsed_s = _parse_time_v_output(result.stderr)

        # Parse prmon output
        prmon_rss_kb = 0
        prmon_wtime_s = 0.0
        if prmon_json.exists():
            with open(prmon_json) as f:
                metrics = json.load(f)
            prmon_rss_kb = metrics["Max"]["rss"]
            prmon_wtime_s = metrics["Max"]["wtime"]

        # Use maximum RSS from both tools for reliability
        max_rss_kb = max(prmon_rss_kb, time_rss_kb)
        # Use CPU time from /usr/bin/time (user+system, more stable than wall time)
        # Fall back to prmon wall time if time -v parsing failed
        wall_time_s = time_cpu_s if time_cpu_s > 0 else prmon_wtime_s

        if max_rss_kb > 0:
            return BenchmarkResult(
                header=header,
                max_rss_kb=max_rss_kb,
                wall_time_s=wall_time_s,
                success=result.returncode == 0,
                error=None if result.returncode == 0 else result.stderr[-500:],
                command=full_cmd,
                prmon_rss_kb=prmon_rss_kb,
                prmon_wtime_s=prmon_wtime_s,
                time_rss_kb=time_rss_kb,
                time_cpu_s=time_cpu_s,
            )

        return BenchmarkResult(
            header=header,
            max_rss_kb=0,
            wall_time_s=0,
            success=False,
            error="No metrics from prmon or time -v",
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
