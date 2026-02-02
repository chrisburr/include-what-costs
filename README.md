# include-what-costs

A standalone tool to analyze C++ header dependencies and compile-time costs.

Given any "root" header file, it:
1. Builds the complete include dependency graph using `gcc -H`
2. Optionally benchmarks compile cost (RSS + time) of each header using `prmon`
3. Generates visualizations for expert review

## Installation

```bash
pip install -e .
```

For YAML config file support:
```bash
pip install -e ".[yaml]"
```

## Usage

### Basic usage (graph only):
```bash
include-what-costs \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --output results/
```

### With prmon benchmarking:
```bash
include-what-costs \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --prmon /path/to/prmon \
    --output results/
```

### Using a config file:
```bash
include-what-costs --config my_config.yaml
```

## Options

| Option | Description |
|--------|-------------|
| `--root` | Root header file to analyze (required) |
| `--compile-commands` | Path to compile_commands.json (required) |
| `--output` | Output directory (default: results) |
| `--prmon` | Path to prmon binary (enables benchmarking) |
| `--source-pattern` | Pattern to match source file for compile flags |
| `--focus` | Focus DOT output on headers matching pattern |
| `--cxx-standard` | C++ standard (default: c++20) |
| `--wrapper` | Wrapper command for gcc (e.g., ./Rec/run) |
| `--config` | Path to YAML config file |

## Output Files

| File | Description |
|------|-------------|
| `include_graph.json` | Full dependency graph + analysis |
| `include_graph.dot` | Graphviz visualization |
| `header_costs.json` | Per-header RSS and compile time (if --prmon) |
| `header_costs.csv` | Same in CSV format (if --prmon) |
| `summary.txt` | Human-readable summary |

## Rendering the Graph

```bash
dot -Tpng results/include_graph.dot -o include_graph.png
dot -Tsvg results/include_graph.dot -o include_graph.svg
```

## LHCb-Specific Usage

```bash
cd ~/stack

# Clean caches first
find . -name 'lib*FunctorCache_*' -print -delete
find . -name 'JIT_includes.h.gch' -print -delete

# Rebuild Rec
make fast/Rec

# Run analysis (using --wrapper to run gcc through the LHCb environment)
pixi run -m include-what-costs include-what-costs \
    --root Rec/Phys/FunctorCore/include/Functors/JIT_includes.h \
    --compile-commands Rec/build.x86_64_v3-el9-gcc13-opt/compile_commands.json \
    --wrapper ./Rec/run \
    --prmon /cvmfs/lhcb.cern.ch/lhcbdirac/versions/v12.0.0-1761556625/Linux-x86_64/bin/prmon \
    --source-pattern FunctorCore \
    --output results/
```

Or using the example config:
```bash
pixi run -m include-what-costs include-what-costs --config include-what-costs/examples/lhcb_config.yaml
```
