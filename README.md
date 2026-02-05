# include-what-costs

A tool to analyze C++ header dependencies and compile-time costs.

## Installation

Using pixi (recommended):
```bash
pixi install
pixi run include-what-costs --help
```

Or with pip:
```bash
pip install -e .
```

### Dependencies

- `prmon` - for memory/time benchmarking (must be in PATH)
- `graphviz` - for graph rendering (specifically `twopi` for radial layout)

## Commands

### `analyze` - Analyze header dependencies and benchmark costs

Builds the complete include dependency graph and optionally benchmarks compile costs.

```bash
include-what-costs analyze \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --output results/
```

With benchmarking (measures RSS and compile time for each header):
```bash
include-what-costs analyze \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --benchmark \
    --output results/
```

Benchmark only the top N headers (by depth, then preprocessed size):
```bash
include-what-costs analyze \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --benchmark 50 \
    --output results/
```

### `consolidate` - Find headers exposing external dependencies

Identifies which of your headers expose a specific external dependency (e.g., DD4hep) and estimates the cost of removing that exposure.

```bash
include-what-costs consolidate \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --prefix /home/user/project \
    --pattern DD4hep
```

Output shows:
- Which of your headers include the external dependency
- How many of your other headers would be affected by removing each include
- Estimated memory savings from removing the dependency

### `trace` - Find include path between headers

Finds and displays the shortest include path(s) between two headers. Useful for understanding why a particular header is being included.

```bash
include-what-costs trace \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --to "DD4hep/Objects.h"
```

By default traces from the root header. Use `--from` to trace from a different starting point:
```bash
include-what-costs trace \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --from "MyHeader.h" \
    --to "DD4hep/Objects.h"
```

Shows up to 10 shortest paths by default. Use `-n` to control:
```bash
# Show only 1 path
include-what-costs trace ... --to "SomeHeader.h" -n 1

# Show up to 20 paths
include-what-costs trace ... --to "SomeHeader.h" -n 20
```

Example output:
```
8 shortest path(s) of length 8, 5 more not shown:

Path 1:
JIT_includes.h
  -> TrackLike.h
    -> KalmanFitResult.h
      -> Measurement.h
        -> DeMuonChamber.h
          -> DeMuonChamber.h
            -> DeIOV.h
              -> DD4hep/Handle.h

Path 2:
...
```

## Common Options

These options are shared across all subcommands:

| Option | Description |
|--------|-------------|
| `--root` | Root header file to analyze (required) |
| `--compile-commands` | Path to compile_commands.json (required) |
| `--prefix` | Path prefix for filtering/display (can be repeated) |
| `--wrapper` | Wrapper command for gcc (e.g., `./Rec/run`) |
| `--config` | Path to YAML config file |

### Subcommand-specific options

**`analyze`:**
| Option | Description |
|--------|-------------|
| `--output` | Output directory (default: results) |
| `--benchmark [N]` | Benchmark headers. Without N: all headers. With N: top N by (depth, preprocessed size) |

**`consolidate`:**
| Option | Description |
|--------|-------------|
| `--pattern` | Substring pattern to match external headers (required) |
| `--output` | Optional JSON output path |

**`trace`:**
| Option | Description |
|--------|-------------|
| `--from` | Source header substring (defaults to --root) |
| `--to` | Target header substring (required) |
| `-n, --max-paths` | Maximum paths to show (default: 10) |

## Output Files (analyze)

| File | Description |
|------|-------------|
| `include_graph.json` | Full dependency graph and analysis data |
| `include_graph.html` | Interactive HTML visualization |
| `header_costs.json` | Per-header RSS and compile time (if benchmarked) |
| `header_costs.csv` | Same in CSV format |
| `summary.txt` | Human-readable summary |

## Using a Config File

YAML config files can specify common options:

```yaml
root: path/to/header.h
compile-commands: build/compile_commands.json
wrapper: ./run_env.sh
prefix:
  - /home/user/project
  - /home/user/other
output: results/
benchmark: 50  # or true for all
```

```bash
include-what-costs analyze --config my_config.yaml
include-what-costs trace --config my_config.yaml --to "SomeHeader.h"
```

## LHCb Usage

For analyzing JIT functor compilation includes:

```bash
cd ~/stack

# Run analysis with benchmarking
pixi run -m include-what-costs/ include-what-costs analyze \
    --root Rec/Phys/FunctorCore/include/Functors/JIT_includes.h \
    --compile-commands Rec/build.x86_64_v3-el9-gcc13-opt/compile_commands.json \
    --wrapper ./Rec/run \
    --prefix ~/stack \
    --benchmark \
    --output results/

# Find what's pulling in DD4hep
pixi run -m include-what-costs/ include-what-costs consolidate \
    --root Rec/Phys/FunctorCore/include/Functors/JIT_includes.h \
    --compile-commands Rec/build.x86_64_v3-el9-gcc13-opt/compile_commands.json \
    --wrapper ./Rec/run \
    --prefix ~/stack \
    --pattern DD4hep

# Trace path to a specific DD4hep header
pixi run -m include-what-costs/ include-what-costs trace \
    --root Rec/Phys/FunctorCore/include/Functors/JIT_includes.h \
    --compile-commands Rec/build.x86_64_v3-el9-gcc13-opt/compile_commands.json \
    --wrapper ./Rec/run \
    --prefix ~/stack \
    --to DD4hep/Handle.h
```

## How It Works

1. **Extract compile flags** from `compile_commands.json` (auto-detects the right source file based on the root header path)

2. **Run `gcc -H`** to get the complete include hierarchy (stderr contains the include tree with depth indicated by dots)

3. **Supplement edges** by parsing `#include` directives directly from headers (gcc -H only shows first inclusion of each header)

4. **Benchmark headers** (if requested) by compiling minimal `.cpp` files that include just that header, measuring RSS and time with `prmon`

5. **Generate outputs**: JSON data, HTML visualization, and summary
