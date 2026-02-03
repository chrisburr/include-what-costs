"""Pyvis rendering with edge-type styling."""

from pathlib import Path

from .classify import EdgeType
from .filter import FilterResult


def render_graph(
    positions: dict[str, tuple[float, float]],
    edges: dict[str, set[str]],
    classified_edges: dict[EdgeType, list[tuple[str, str]]],
    filter_result: FilterResult | None,
    include_counts: dict[str, int],
    output_path: Path,
    root_name: str | None = None,
) -> None:
    """Render graph with pyvis.

    Args:
        positions: (x, y) positions for each header.
        edges: Full adjacency list (parent -> children).
        classified_edges: Edges classified by type.
        filter_result: Optional filter result for styling filtered nodes.
        include_counts: Number of times each header is included.
        output_path: Path to write the HTML file.
        root_name: Optional name of the root file.
    """
    from pyvis.network import Network

    # Determine which nodes to include
    if filter_result:
        visible_nodes = filter_result.included_nodes | filter_result.intermediate_nodes
    else:
        visible_nodes = set(positions.keys())

    # Create network with physics disabled (we set fixed positions)
    net = Network(
        height="900px",
        width="100%",
        bgcolor="#ffffff",
        directed=True,
    )
    net.toggle_physics(False)

    # Track header names for edges
    header_to_name: dict[str, str] = {}

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
    for header, (x, y) in positions.items():
        if header not in visible_nodes:
            continue

        name = Path(header).name
        header_to_name[header] = name
        count = include_counts.get(header, 0)

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

        # Get depth from position (for label)
        # This is approximate - we could pass header_to_depth but positions encode it
        net.add_node(
            name,
            label=f"{name}\n({count}x)" if not is_intermediate else name,
            title=f"{header}\nIncluded {count}x",
            x=x,
            y=y,
            fixed=True,
            color=color,
            shape="box",
            font={"size": font_size},
            size=15 if is_intermediate else 25,
        )

    # Edge styles by type
    edge_styles = {
        EdgeType.TREE: {"color": "#cccccc", "width": 1},  # light gray, straight
        EdgeType.BACK: {"color": "rgba(255,0,0,0.3)", "width": 1},  # red, lower opacity
        EdgeType.SAME_LEVEL: {"color": "rgba(0,0,255,0.3)", "width": 1},  # blue, lower opacity
        EdgeType.FORWARD_SKIP: {"color": "rgba(128,0,128,0.3)", "width": 1},  # purple
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
        for header, (x, y) in positions.items():
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
            "arrows": {"to": {"enabled": true, "scaleFactor": 0.5}},
            "smooth": {"type": "continuous"},
            "selectionWidth": 2,
            "hoverWidth": 2
        },
        "nodes": {
            "borderWidth": 1,
            "borderWidthSelected": 3
        }
    }
    """)

    net.save_graph(str(output_path))

    # Inject custom JavaScript for better selection highlighting
    _inject_highlight_script(output_path)


def _inject_highlight_script(output_file: Path) -> None:
    """Inject custom JavaScript for better selection highlighting.

    When a node is selected, this highlights:
    - Incoming edges (headers that include this one) in blue
    - Outgoing edges (headers this one includes) in green
    """
    with open(output_file, "r") as f:
        html = f.read()

    # JavaScript to add after the network is created
    custom_script = """
    <script type="text/javascript">
    // Wait for network to be ready
    document.addEventListener('DOMContentLoaded', function() {
        // Give vis.js time to initialize
        setTimeout(function() {
            if (typeof network === 'undefined') return;

            // Create info panel
            var infoPanel = document.createElement('div');
            infoPanel.id = 'infoPanel';
            infoPanel.style.cssText = 'position:fixed;top:10px;right:10px;padding:15px;background:white;border:1px solid #ccc;border-radius:5px;font-family:monospace;font-size:12px;max-width:400px;display:none;z-index:1000;box-shadow:0 2px 10px rgba(0,0,0,0.1);';
            document.body.appendChild(infoPanel);

            // Create legend
            var legend = document.createElement('div');
            legend.innerHTML = '<div style="position:fixed;bottom:10px;right:10px;padding:10px;background:white;border:1px solid #ccc;border-radius:5px;font-family:sans-serif;font-size:11px;">' +
                '<div><span style="display:inline-block;width:20px;height:3px;background:#2ecc71;margin-right:5px;vertical-align:middle;"></span> includes (outgoing)</div>' +
                '<div><span style="display:inline-block;width:20px;height:3px;background:#3498db;margin-right:5px;vertical-align:middle;"></span> included by (incoming)</div>' +
                '<div style="margin-top:5px;border-top:1px solid #eee;padding-top:5px;">' +
                '<div><span style="display:inline-block;width:20px;height:3px;background:#cccccc;margin-right:5px;vertical-align:middle;"></span> tree edge</div>' +
                '<div><span style="display:inline-block;width:20px;height:3px;background:rgba(255,0,0,0.5);margin-right:5px;vertical-align:middle;"></span> back edge</div>' +
                '<div><span style="display:inline-block;width:20px;height:3px;background:rgba(0,0,255,0.5);margin-right:5px;vertical-align:middle;"></span> same-level edge</div>' +
                '</div>' +
                '</div>';
            document.body.appendChild(legend);

            var originalColors = {};

            network.on('selectNode', function(params) {
                var selectedNode = params.nodes[0];
                var connectedEdges = network.getConnectedEdges(selectedNode);
                var incoming = [];
                var outgoing = [];

                // Store original colors and categorize edges
                connectedEdges.forEach(function(edgeId) {
                    var edge = edges.get(edgeId);
                    if (!originalColors[edgeId]) {
                        originalColors[edgeId] = edge.color;
                    }

                    if (edge.to === selectedNode) {
                        incoming.push({edge: edgeId, from: edge.from});
                        edges.update({id: edgeId, color: {color: '#3498db', highlight: '#3498db'}, width: 2});
                    } else {
                        outgoing.push({edge: edgeId, to: edge.to});
                        edges.update({id: edgeId, color: {color: '#2ecc71', highlight: '#2ecc71'}, width: 2});
                    }
                });

                // Update info panel
                infoPanel.innerHTML = '<strong>' + selectedNode + '</strong><br><br>' +
                    '<span style="color:#2ecc71">▶ Includes ' + outgoing.length + ' headers:</span><br>' +
                    outgoing.slice(0, 10).map(function(e) { return '&nbsp;&nbsp;' + e.to; }).join('<br>') +
                    (outgoing.length > 10 ? '<br>&nbsp;&nbsp;... and ' + (outgoing.length - 10) + ' more' : '') +
                    '<br><br>' +
                    '<span style="color:#3498db">◀ Included by ' + incoming.length + ' headers:</span><br>' +
                    incoming.slice(0, 10).map(function(e) { return '&nbsp;&nbsp;' + e.from; }).join('<br>') +
                    (incoming.length > 10 ? '<br>&nbsp;&nbsp;... and ' + (incoming.length - 10) + ' more' : '');
                infoPanel.style.display = 'block';
            });

            network.on('deselectNode', function(params) {
                // Restore original edge colors
                Object.keys(originalColors).forEach(function(edgeId) {
                    edges.update({id: edgeId, color: originalColors[edgeId], width: 1});
                });
                originalColors = {};
                infoPanel.style.display = 'none';
            });

        }, 500);
    });
    </script>
    """

    # Insert before closing body tag
    html = html.replace("</body>", custom_script + "</body>")

    with open(output_file, "w") as f:
        f.write(html)
