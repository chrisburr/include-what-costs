# include-what-costs

A tool to analyze C++ header dependencies and compile-time costs.

Given a "root" header file, it:
1. Builds the complete include dependency graph using `gcc -H`
2. Benchmarks compile cost (RSS and time) of each direct include using `prmon`
3. Generates a radial graph visualization showing the dependency structure

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

## Usage

### Basic usage:
```bash
include-what-costs \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --output results/
```

### Filter to specific paths:
```bash
include-what-costs \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --prefix /home/user/project \
    --output results/
```

### Graph only (skip benchmarking):
```bash
include-what-costs \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --no-benchmark \
    --output results/
```

### Using a wrapper command:
For projects that require a specific environment (e.g., LHCb):
```bash
include-what-costs \
    --root path/to/header.h \
    --compile-commands build/compile_commands.json \
    --wrapper ./run_env.sh \
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
| `--prefix` | Only show headers under this path prefix in the graph |
| `--wrapper` | Wrapper command for gcc (e.g., `./Rec/run`) |
| `--no-benchmark` | Skip header cost benchmarking |
| `--benchmark-limit N` | Benchmark only the N largest headers (by depth, then preprocessed size) |
| `--config` | Path to YAML config file |

## Output Files

| File | Description |
|------|-------------|
| `include_graph.json` | Full dependency graph and analysis data |
| `include_graph.html` | Interactive HTML visualization (with pyvis) |
| `include_graph.dot` | Graphviz DOT file |
| `include_graph.png` | Rendered graph (radial layout) |
| `include_graph.svg` | Rendered graph (SVG format) |
| `header_costs.json` | Per-header RSS and compile time |
| `header_costs.csv` | Same in CSV format |
| `summary.txt` | Human-readable summary |

## Graph Visualization

The graph uses a radial layout (`twopi`) with:
- **Root node** (blue, center): The analyzed header file
- **Direct includes**: Connected directly to root
- **Node colors**: Based on include count (red > orange > yellow > white)

To manually render with different options:
```bash
# Radial layout (default)
twopi -Tpng results/include_graph.dot -o graph.png

# Hierarchical layout
dot -Tpng results/include_graph.dot -o graph.png

# Force-directed layout
fdp -Tpng results/include_graph.dot -o graph.png
```

## LHCb Usage

For analyzing JIT functor compilation includes:

```bash
cd ~/stack

# Clean caches first (optional, for accurate benchmarking)
find . -name 'lib*FunctorCache_*' -print -delete
find . -name 'JIT_includes.h.gch' -print -delete
make fast/Rec

# Run analysis
./Rec/run include-what-costs \
    --root Rec/Phys/FunctorCore/include/Functors/JIT_includes.h \
    --compile-commands Rec/build.x86_64_v3-el9-gcc13-opt/compile_commands.json \
    --wrapper ./Rec/run \
    --prefix ~/stack \
    --output results/
```

Or using pixi:
```bash
pixi run -m include-what-costs include-what-costs \
    --root Rec/Phys/FunctorCore/include/Functors/JIT_includes.h \
    --compile-commands Rec/build.x86_64_v3-el9-gcc13-opt/compile_commands.json \
    --wrapper ./Rec/run \
    --prefix ~/stack \
    --output results/
```

## Config File Format

YAML config files can specify any CLI option:

```yaml
root: path/to/header.h
compile-commands: build/compile_commands.json
wrapper: ./run_env.sh
prefix: /home/user/project
output: results/
```

## How It Works

1. **Extract compile flags** from `compile_commands.json` (auto-detects the right source file based on the root header path)

2. **Run `gcc -H`** to get the complete include hierarchy (stderr contains the include tree with depth indicated by dots)

3. **Parse direct includes** from the root header file itself (more accurate than relying on gcc -H depth tracking)

4. **Benchmark each direct include** by compiling a minimal `.cpp` that includes just that header, measuring RSS and time with `prmon`

5. **Generate outputs**: JSON data, DOT graph, rendered images, and summary
