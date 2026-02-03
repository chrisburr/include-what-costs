"""Pyvis rendering with edge-type styling."""

import base64
import math
from pathlib import Path

from .classify import EdgeType
from .filter import FilterResult


def _create_rotated_label_svg(
    label: str,
    angle: float,
    color: str,
    font_size: int = 10,
) -> str:
    """Create SVG with text rotated to align with radial direction.

    Text is rotated so it reads outward from center, flipping on the left
    side so text is never upside-down.

    Args:
        label: Text to display.
        angle: Angle in radians from center.
        color: Background color for the label box.
        font_size: Font size in pixels.

    Returns:
        Data URL for the SVG image.
    """
    # Convert to degrees for SVG transform
    angle_deg = math.degrees(angle)

    # Flip text on left side so it's never upside-down
    if angle_deg > 90 or angle_deg < -90:
        angle_deg += 180

    # Estimate text dimensions (approximate)
    char_width = font_size * 0.6
    text_width = len(label) * char_width
    text_height = font_size * 1.4
    padding = 4

    # SVG dimensions need to accommodate rotated text
    # Use the diagonal as the dimension to ensure text fits at any angle
    svg_size = max(text_width, text_height) + padding * 2 + 10
    center = svg_size / 2

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{svg_size}" height="{svg_size}">
  <g transform="translate({center}, {center}) rotate({angle_deg})">
    <rect x="{-text_width/2 - padding}" y="{-text_height/2}"
          width="{text_width + padding*2}" height="{text_height}"
          fill="{color}" stroke="#888" stroke-width="1" rx="3"/>
    <text x="0" y="{font_size * 0.35}"
          text-anchor="middle" font-family="monospace" font-size="{font_size}"
          fill="#333">{label}</text>
  </g>
</svg>'''

    # Encode as data URL
    encoded = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{encoded}"


def _compute_thresholds(values: list[float]) -> tuple[float, float, float]:
    """Return (50th, 75th, 90th) percentile thresholds.

    Args:
        values: List of numeric values.

    Returns:
        Tuple of (p50, p75, p90) threshold values.
    """
    if not values:
        return (0, 0, 0)
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return (
        sorted_vals[int(n * 0.5)],
        sorted_vals[int(n * 0.75)],
        sorted_vals[min(int(n * 0.9), n - 1)],
    )


def render_graph(
    positions: dict[str, tuple[float, float, float]],
    edges: dict[str, set[str]],
    classified_edges: dict[EdgeType, list[tuple[str, str]]],
    filter_result: FilterResult | None,
    include_counts: dict[str, int],
    output_path: Path,
    root_name: str | None = None,
    benchmark_data: dict[str, dict] | None = None,
) -> None:
    """Render graph with pyvis.

    Args:
        positions: (x, y, angle) positions for each header.
        edges: Full adjacency list (parent -> children).
        classified_edges: Edges classified by type.
        filter_result: Optional filter result for styling filtered nodes.
        include_counts: Number of times each header is included.
        output_path: Path to write the HTML file.
        root_name: Optional name of the root file.
        benchmark_data: Optional dict mapping header paths to {rss_kb, time_s}.
    """
    import json as json_module

    from pyvis.network import Network

    # Determine which nodes to include
    if filter_result:
        visible_nodes = filter_result.included_nodes | filter_result.intermediate_nodes
    else:
        visible_nodes = set(positions.keys())

    # Compute percentile thresholds for benchmark data
    benchmark_data = benchmark_data or {}
    rss_values = [d["rss_kb"] for d in benchmark_data.values()]
    time_values = [d["time_s"] for d in benchmark_data.values()]
    rss_thresholds = _compute_thresholds(rss_values)
    time_thresholds = _compute_thresholds(time_values)
    has_benchmark_data = len(benchmark_data) > 0

    # Create network with physics disabled (we set fixed positions)
    net = Network(
        height="100vh",
        width="100%",
        bgcolor="#ffffff",
        directed=True,
    )
    net.toggle_physics(False)

    # Track header names for edges and node data for JS
    header_to_name: dict[str, str] = {}
    node_data: dict[str, dict] = {}  # For JS toggle

    # Add root node at center if provided
    if root_name:
        net.add_node(
            root_name,
            label=root_name,
            title=f"{root_name}\n(root)",
            x=0,
            y=0,
            fixed=True,
            color="#87CEEB",  # light blue
            shape="box",
            font={"size": 12},
        )

    # Add nodes
    for header, (x, y, angle) in positions.items():
        if header not in visible_nodes:
            continue

        name = Path(header).name
        header_to_name[header] = name
        count = include_counts.get(header, 0)

        # Get benchmark data for this header
        bench = benchmark_data.get(header, {})
        rss_kb = bench.get("rss_kb", 0)
        time_s = bench.get("time_s", 0)
        has_bench = header in benchmark_data

        # Determine if this is an intermediate (filtered-out but shown) node
        is_intermediate = filter_result and header in filter_result.intermediate_nodes

        # Color based on include count (grayed if intermediate)
        if is_intermediate:
            color = "#d0d0d0"  # gray for intermediate
            font_size = 8
        elif count > 10:
            color = "#ff6b6b"  # red
            font_size = 10
        elif count > 5:
            color = "#ffa94d"  # orange
            font_size = 10
        elif count > 2:
            color = "#ffd43b"  # yellow
            font_size = 10
        else:
            color = "#e9ecef"  # light gray
            font_size = 10

        # Create SVG with rotated label
        label_text = name if is_intermediate else f"{name} ({count}x)"
        svg_url = _create_rotated_label_svg(label_text, angle, color, font_size)

        # Build tooltip with all metrics
        tooltip_lines = [header, f"Included {count}x"]
        if has_bench:
            tooltip_lines.append(f"RSS: {rss_kb / 1024:.1f} MB")
            tooltip_lines.append(f"Time: {time_s:.1f}s")
        tooltip = "\n".join(tooltip_lines)

        net.add_node(
            name,
            label=" ",  # Space to suppress default label
            title=tooltip,
            x=x,
            y=y,
            fixed=True,
            shape="image",
            image=svg_url,
            size=15 if is_intermediate else 25,
            font={"size": 0},  # Hide any text label
        )

        # Store node data for JS toggle
        node_data[name] = {
            "name": name,
            "count": count,
            "rss_kb": rss_kb,
            "time_s": time_s,
            "has_bench": has_bench,
            "angle": angle,
            "is_intermediate": is_intermediate,
        }

    # Edge styles by type
    edge_styles = {
        EdgeType.TREE: {"color": "#cccccc", "width": 0.5},  # light gray, straight
        EdgeType.BACK: {"color": "rgba(255,0,0,0.3)", "width": 0.5},  # red, lower opacity
        EdgeType.SAME_LEVEL: {"color": "rgba(0,0,255,0.3)", "width": 0.5},  # blue, lower opacity
        EdgeType.FORWARD_SKIP: {"color": "rgba(128,0,128,0.3)", "width": 0.5},  # purple
    }

    # Add edges by type
    for edge_type, edge_list in classified_edges.items():
        style = edge_styles[edge_type]
        for parent, child in edge_list:
            if parent not in visible_nodes or child not in visible_nodes:
                continue
            parent_name = header_to_name.get(parent)
            child_name = header_to_name.get(child)
            if parent_name and child_name:
                try:
                    net.add_edge(
                        parent_name,
                        child_name,
                        color=style["color"],
                        width=style["width"],
                    )
                except Exception:
                    pass  # Skip if edge already exists or nodes missing

    # Add edges from root to depth-1 nodes
    if root_name:
        for header, (x, y, angle) in positions.items():
            if header not in visible_nodes:
                continue
            # Check if this is a depth-1 node (connected to root in tree edges)
            # We need to check if it's not a child in any tree edge
            is_depth_1 = True
            for parent, child in classified_edges[EdgeType.TREE]:
                if child == header:
                    is_depth_1 = False
                    break
            if is_depth_1:
                name = header_to_name.get(header)
                if name:
                    try:
                        net.add_edge(root_name, name, color="#888888")
                    except Exception:
                        pass

    # Configure interaction options with highlighting
    net.set_options("""
    {
        "physics": {"enabled": false},
        "interaction": {
            "navigationButtons": true,
            "zoomView": true,
            "dragView": true,
            "hover": true,
            "selectConnectedEdges": true,
            "tooltipDelay": 100
        },
        "edges": {
            "arrows": {"to": {"enabled": true, "scaleFactor": 0.3}},
            "smooth": {"type": "continuous"},
            "width": 0.5,
            "selectionWidth": 1.5,
            "hoverWidth": 1.5
        },
        "nodes": {
            "borderWidth": 1,
            "borderWidthSelected": 3
        }
    }
    """)

    net.save_graph(str(output_path))

    # Inject custom JavaScript for better selection highlighting and color toggle
    _inject_highlight_script(
        output_path,
        node_data=node_data,
        rss_thresholds=rss_thresholds,
        time_thresholds=time_thresholds,
        has_benchmark_data=has_benchmark_data,
    )


def _inject_highlight_script(
    output_file: Path,
    node_data: dict[str, dict],
    rss_thresholds: tuple[float, float, float],
    time_thresholds: tuple[float, float, float],
    has_benchmark_data: bool,
) -> None:
    """Inject custom JavaScript for selection highlighting and color mode toggle.

    When a node is selected, this highlights:
    - Incoming edges (headers that include this one) in blue
    - Outgoing edges (headers this one includes) in green

    Also adds a toggle UI to switch between coloring modes:
    - Include count (default)
    - RSS memory (if benchmark data available)
    - Compile time (if benchmark data available)

    Args:
        output_file: Path to the HTML file to modify.
        node_data: Dict mapping node names to their metrics.
        rss_thresholds: (p50, p75, p90) thresholds for RSS.
        time_thresholds: (p50, p75, p90) thresholds for time.
        has_benchmark_data: Whether benchmark data is available.
    """
    import json as json_module

    with open(output_file, "r") as f:
        html = f.read()

    # Serialize data for JavaScript
    node_data_json = json_module.dumps(node_data)
    rss_thresholds_json = json_module.dumps(rss_thresholds)
    time_thresholds_json = json_module.dumps(time_thresholds)

    # JavaScript to add after the network is created
    custom_script = f"""
    <script type="text/javascript">
    // Node data for color toggle
    var nodeData = {node_data_json};
    var rssThresholds = {rss_thresholds_json};
    var timeThresholds = {time_thresholds_json};
    var hasBenchmarkData = {'true' if has_benchmark_data else 'false'};
    var currentMode = hasBenchmarkData ? 'rss' : 'count';

    // Create rotated label SVG (mirrors Python implementation)
    function createRotatedLabelSvg(label, angle, color, fontSize) {{
        fontSize = fontSize || 10;
        // Convert to degrees
        var angleDeg = angle * 180 / Math.PI;
        // Flip text on left side
        if (angleDeg > 90 || angleDeg < -90) {{
            angleDeg += 180;
        }}
        // Estimate text dimensions
        var charWidth = fontSize * 0.6;
        var textWidth = label.length * charWidth;
        var textHeight = fontSize * 1.4;
        var padding = 4;
        var svgSize = Math.max(textWidth, textHeight) + padding * 2 + 10;
        var center = svgSize / 2;

        var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + svgSize + '" height="' + svgSize + '">' +
            '<g transform="translate(' + center + ', ' + center + ') rotate(' + angleDeg + ')">' +
            '<rect x="' + (-textWidth/2 - padding) + '" y="' + (-textHeight/2) + '"' +
            ' width="' + (textWidth + padding*2) + '" height="' + textHeight + '"' +
            ' fill="' + color + '" stroke="#888" stroke-width="1" rx="3"/>' +
            '<text x="0" y="' + (fontSize * 0.35) + '"' +
            ' text-anchor="middle" font-family="monospace" font-size="' + fontSize + '"' +
            ' fill="#333">' + label + '</text>' +
            '</g></svg>';

        return 'data:image/svg+xml;base64,' + btoa(svg);
    }}

    // Get color based on value and thresholds
    function getColorForValue(value, thresholds, hasData) {{
        if (!hasData) {{
            return '#d0d0d0';  // Gray for no data
        }}
        var p50 = thresholds[0], p75 = thresholds[1], p90 = thresholds[2];
        if (value >= p90) return '#ff6b6b';  // Red
        if (value >= p75) return '#ffa94d';  // Orange
        if (value >= p50) return '#ffd43b';  // Yellow
        return '#e9ecef';  // Light gray
    }}

    // Get color for include count mode
    function getCountColor(count) {{
        if (count > 10) return '#ff6b6b';  // Red
        if (count > 5) return '#ffa94d';   // Orange
        if (count > 2) return '#ffd43b';   // Yellow
        return '#e9ecef';  // Light gray
    }}

    // Update node colors based on mode
    function updateNodeColors(mode) {{
        currentMode = mode;
        var updates = [];

        Object.keys(nodeData).forEach(function(nodeName) {{
            var data = nodeData[nodeName];
            if (data.is_intermediate) return;  // Skip intermediate nodes

            var color, label;
            var fontSize = 10;

            if (mode === 'count') {{
                color = getCountColor(data.count);
                label = data.name + ' (' + data.count + 'x)';
            }} else if (mode === 'rss') {{
                color = getColorForValue(data.rss_kb, rssThresholds, data.has_bench);
                if (data.has_bench) {{
                    label = data.name + ' (' + (data.rss_kb / 1024).toFixed(0) + 'MB)';
                }} else {{
                    label = data.name + ' (N/A)';
                }}
            }} else if (mode === 'time') {{
                color = getColorForValue(data.time_s, timeThresholds, data.has_bench);
                if (data.has_bench) {{
                    label = data.name + ' (' + data.time_s.toFixed(1) + 's)';
                }} else {{
                    label = data.name + ' (N/A)';
                }}
            }}

            var svgUrl = createRotatedLabelSvg(label, data.angle, color, fontSize);
            updates.push({{id: nodeName, image: svgUrl}});
        }});

        nodes.update(updates);
        updateLegend(mode);
    }}

    // Update legend based on mode
    function updateLegend(mode) {{
        var legendContent = document.getElementById('colorLegendContent');
        if (!legendContent) return;

        var html = '';
        if (mode === 'count') {{
            html = '<div><span class="legend-color" style="background:#ff6b6b;"></span> &gt;10 includes</div>' +
                   '<div><span class="legend-color" style="background:#ffa94d;"></span> &gt;5 includes</div>' +
                   '<div><span class="legend-color" style="background:#ffd43b;"></span> &gt;2 includes</div>' +
                   '<div><span class="legend-color" style="background:#e9ecef;"></span> &le;2 includes</div>';
        }} else {{
            var unit = mode === 'rss' ? 'RSS' : 'Time';
            html = '<div><span class="legend-color" style="background:#ff6b6b;"></span> &ge;90th percentile</div>' +
                   '<div><span class="legend-color" style="background:#ffa94d;"></span> &ge;75th percentile</div>' +
                   '<div><span class="legend-color" style="background:#ffd43b;"></span> &ge;50th percentile</div>' +
                   '<div><span class="legend-color" style="background:#e9ecef;"></span> &lt;50th percentile</div>' +
                   '<div><span class="legend-color" style="background:#d0d0d0;"></span> No data</div>';
        }}
        legendContent.innerHTML = html;
    }}

    // Wait for network to be ready
    document.addEventListener('DOMContentLoaded', function() {{
        // Give vis.js time to initialize
        setTimeout(function() {{
            if (typeof network === 'undefined') return;

            // Create toggle UI (only if benchmark data exists)
            if (hasBenchmarkData) {{
                var togglePanel = document.createElement('div');
                togglePanel.id = 'togglePanel';
                togglePanel.innerHTML = '<div style="position:fixed;top:10px;left:10px;padding:10px;background:white;border:1px solid #ccc;border-radius:5px;font-family:sans-serif;font-size:12px;z-index:1000;box-shadow:0 2px 10px rgba(0,0,0,0.1);">' +
                    '<div style="font-weight:bold;margin-bottom:8px;">Color by:</div>' +
                    '<label style="display:block;cursor:pointer;margin:4px 0;"><input type="radio" name="colorMode" value="count"> Include count</label>' +
                    '<label style="display:block;cursor:pointer;margin:4px 0;"><input type="radio" name="colorMode" value="rss" checked> RSS memory</label>' +
                    '<label style="display:block;cursor:pointer;margin:4px 0;"><input type="radio" name="colorMode" value="time"> Compile time</label>' +
                    '</div>';
                document.body.appendChild(togglePanel);

                // Add event listeners to radio buttons
                var radios = document.querySelectorAll('input[name="colorMode"]');
                radios.forEach(function(radio) {{
                    radio.addEventListener('change', function() {{
                        updateNodeColors(this.value);
                    }});
                }});

                // Apply RSS coloring by default
                updateNodeColors('rss');
            }}

            // Create info panel (left side, below toggle if present)
            var infoPanel = document.createElement('div');
            infoPanel.id = 'infoPanel';
            var infoPanelTop = hasBenchmarkData ? '140px' : '10px';
            infoPanel.style.cssText = 'position:fixed;top:' + infoPanelTop + ';left:10px;padding:15px;background:white;border:1px solid #ccc;border-radius:5px;font-family:monospace;font-size:12px;max-width:400px;display:none;z-index:1000;box-shadow:0 2px 10px rgba(0,0,0,0.1);';
            document.body.appendChild(infoPanel);

            // Create legend (upper right, floating)
            var legend = document.createElement('div');
            legend.innerHTML = '<div style="position:fixed;top:10px;right:10px;padding:10px;background:white;border:1px solid #ccc;border-radius:5px;font-family:sans-serif;font-size:11px;z-index:1000;box-shadow:0 2px 10px rgba(0,0,0,0.1);">' +
                '<div style="font-weight:bold;margin-bottom:5px;">Node colors:</div>' +
                '<div id="colorLegendContent">' +
                (hasBenchmarkData ?
                    '<div><span class="legend-color" style="background:#ff6b6b;"></span> &ge;90th percentile</div>' +
                    '<div><span class="legend-color" style="background:#ffa94d;"></span> &ge;75th percentile</div>' +
                    '<div><span class="legend-color" style="background:#ffd43b;"></span> &ge;50th percentile</div>' +
                    '<div><span class="legend-color" style="background:#e9ecef;"></span> &lt;50th percentile</div>' +
                    '<div><span class="legend-color" style="background:#d0d0d0;"></span> No data</div>'
                :
                    '<div><span class="legend-color" style="background:#ff6b6b;"></span> &gt;10 includes</div>' +
                    '<div><span class="legend-color" style="background:#ffa94d;"></span> &gt;5 includes</div>' +
                    '<div><span class="legend-color" style="background:#ffd43b;"></span> &gt;2 includes</div>' +
                    '<div><span class="legend-color" style="background:#e9ecef;"></span> &le;2 includes</div>'
                ) +
                '</div>' +
                '<div style="margin-top:8px;border-top:1px solid #eee;padding-top:8px;font-weight:bold;margin-bottom:5px;">Edge colors:</div>' +
                '<div><span class="legend-line" style="background:#2ecc71;"></span> includes (outgoing)</div>' +
                '<div><span class="legend-line" style="background:#3498db;"></span> included by (incoming)</div>' +
                '<div style="margin-top:5px;border-top:1px solid #eee;padding-top:5px;">' +
                '<div><span class="legend-line" style="background:#cccccc;"></span> tree edge</div>' +
                '<div><span class="legend-line" style="background:rgba(255,0,0,0.5);"></span> back edge</div>' +
                '<div><span class="legend-line" style="background:rgba(0,0,255,0.5);"></span> same-level edge</div>' +
                '</div>' +
                '</div>';
            document.body.appendChild(legend);

            // Add CSS for legend and full-screen canvas
            var style = document.createElement('style');
            style.textContent = 'html, body {{ margin: 0; padding: 0; overflow: hidden; }}' +
                '.legend-color {{ display:inline-block;width:12px;height:12px;margin-right:5px;vertical-align:middle;border:1px solid #888;border-radius:2px; }}' +
                '.legend-line {{ display:inline-block;width:20px;height:3px;margin-right:5px;vertical-align:middle; }}';
            document.head.appendChild(style);

            var originalColors = {{}};

            network.on('selectNode', function(params) {{
                var selectedNode = params.nodes[0];

                // Find all downstream nodes (transitive)
                var downstreamNodes = new Set();
                var queue = [selectedNode];
                while (queue.length > 0) {{
                    var current = queue.shift();
                    var currentEdges = network.getConnectedEdges(current);
                    currentEdges.forEach(function(edgeId) {{
                        var edge = edges.get(edgeId);
                        if (edge.from === current && !downstreamNodes.has(edge.to)) {{
                            downstreamNodes.add(edge.to);
                            queue.push(edge.to);
                        }}
                    }});
                }}

                // Get direct connections for info panel
                var connectedEdges = network.getConnectedEdges(selectedNode);
                var directIncoming = [];
                var directOutgoing = [];
                connectedEdges.forEach(function(edgeId) {{
                    var edge = edges.get(edgeId);
                    if (edge.to === selectedNode) {{
                        directIncoming.push(edge.from);
                    }} else {{
                        directOutgoing.push(edge.to);
                    }}
                }});

                // Highlight all edges in the downstream subgraph
                var allEdges = edges.get();
                allEdges.forEach(function(edge) {{
                    if (!originalColors[edge.id]) {{
                        originalColors[edge.id] = edge.color;
                    }}

                    if (edge.to === selectedNode) {{
                        // Direct incoming edge
                        edges.update({{id: edge.id, color: {{color: '#3498db', highlight: '#3498db'}}, width: 1.5}});
                    }} else if (edge.from === selectedNode || (downstreamNodes.has(edge.from) && downstreamNodes.has(edge.to))) {{
                        // Downstream edge (from selected or between downstream nodes)
                        edges.update({{id: edge.id, color: {{color: '#2ecc71', highlight: '#2ecc71'}}, width: 1.5}});
                    }} else if (downstreamNodes.has(edge.to) && (edge.from === selectedNode || downstreamNodes.has(edge.from))) {{
                        // Edge into downstream subgraph
                        edges.update({{id: edge.id, color: {{color: '#2ecc71', highlight: '#2ecc71'}}, width: 1.5}});
                    }}
                }});

                // Update info panel
                infoPanel.innerHTML = '<strong>' + selectedNode + '</strong><br><br>' +
                    '<span style="color:#2ecc71">&#9654; Includes ' + directOutgoing.length + ' direct, ' + downstreamNodes.size + ' transitive:</span><br>' +
                    directOutgoing.slice(0, 10).map(function(n) {{ return '&nbsp;&nbsp;' + n; }}).join('<br>') +
                    (directOutgoing.length > 10 ? '<br>&nbsp;&nbsp;... and ' + (directOutgoing.length - 10) + ' more direct' : '') +
                    '<br><br>' +
                    '<span style="color:#3498db">&#9664; Included by ' + directIncoming.length + ' headers:</span><br>' +
                    directIncoming.slice(0, 10).map(function(n) {{ return '&nbsp;&nbsp;' + n; }}).join('<br>') +
                    (directIncoming.length > 10 ? '<br>&nbsp;&nbsp;... and ' + (directIncoming.length - 10) + ' more' : '');
                infoPanel.style.display = 'block';
            }});

            network.on('deselectNode', function(params) {{
                // Restore original edge colors
                Object.keys(originalColors).forEach(function(edgeId) {{
                    edges.update({{id: edgeId, color: originalColors[edgeId], width: 0.5}});
                }});
                originalColors = {{}};
                infoPanel.style.display = 'none';
            }});

        }}, 500);
    }});
    </script>
    """

    # Insert before closing body tag
    html = html.replace("</body>", custom_script + "</body>")

    with open(output_file, "w") as f:
        f.write(html)
