"""
TestPulse — Graph Reporter
Adapted from Graphify (Graphify-Labs/graphify: report.py).
Generates human-readable Markdown reports (GRAPH_REPORT.md) and interactive HTML visualizers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import networkx as nx

from testpulse.graph.queries import (
    find_import_cycles,
    get_node_line_count,
    god_nodes,
    is_trivial_function,
    select_integration_targets,
    select_unit_targets,
)


def generate_report(G: nx.DiGraph, output_path: str | Path | None = None) -> str:
    """
    Generates a clean, human-readable Markdown report summarizing the structural
    knowledge graph, detected FastAPI routes, God nodes, and architectural health.
    """
    # 1. Overview counts
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()

    file_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "file"]
    function_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") in ("function", "method")]
    class_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "class"]

    extracted_edges = [d for _, _, d in G.edges(data=True) if d.get("confidence") == "EXTRACTED"]
    inferred_edges = [d for _, _, d in G.edges(data=True) if d.get("confidence") == "INFERRED"]

    # 2. Entry points
    integration_targets = select_integration_targets(G, max_targets=50)

    # 3. God nodes & business logic
    top_god_nodes = god_nodes(G, top_n=10)
    unit_targets = select_unit_targets(G, max_targets=10)

    # 4. Trivial functions filtered
    trivial_functions: list[dict[str, Any]] = []
    for _node_id, attrs in G.nodes(data=True):
        if is_trivial_function(attrs):
            line_count = get_node_line_count(attrs)
            trivial_functions.append({
                "symbol": str(attrs.get("label", "")),
                "file": str(attrs.get("source_file", "")),
                "lines": line_count,
            })

    # 5. Cycles & warnings
    cycles = find_import_cycles(G, max_cycle_length=6, top_n=10)

    # Build Markdown document
    lines: list[str] = [
        "# TestPulse — Structural AST Knowledge Graph Report",
        "",
        "> Generated automatically by TestPulse Native AST Engine (adapted from Graphify-Labs/graphify).",
        "",
        "---",
        "",
        "## 1. Graph Overview",
        "",
        "| Metric | Count | Details |",
        "|---|---|---|",
        f"| **Files Scanned** | `{len(file_nodes)}` | Python and JS/TS source modules |",
        f"| **Total Symbols** | `{total_nodes}` | `{len(function_nodes)}` functions/methods, `{len(class_nodes)}` classes |",
        f"| **Total Edges** | `{total_edges}` | Directed call, import, and containment relations |",
        f"| **Explicit Edges (EXTRACTED)** | `{len(extracted_edges)}` | Verified AST imports, containment, Depends() |",
        f"| **Inferred Edges (INFERRED)** | `{len(inferred_edges)}` | Resolved call invocations |",
        "",
        "---",
        "",
        "## 2. Detected FastAPI Entry Points",
        "",
    ]

    if integration_targets:
        lines.extend([
            "| Method | Route Path | Handler Symbol | File Location | Injected Dependencies | Downstream Calls |",
            "|---|---|---|---|---|---|",
        ])
        for it in integration_targets:
            deps_str = ", ".join(f"`{d}`" for d in it["dependencies"]) or "*None*"
            down_str = f"{len(it['downstream_targets'])} symbol(s)"
            loc_str = f"`{it['source_file']}:L{it['line_start']}`"
            lines.append(f"| **{it['http_method']}** | `{it['route_path']}` | `{it['symbol']}` | {loc_str} | {deps_str} | {down_str} |")
        lines.append("")
    else:
        lines.extend(["*No FastAPI route entry points detected in scanned files.*", ""])

    lines.extend([
        "---",
        "",
        "## 3. High-Priority Business Logic & God Nodes",
        "",
        "### Top Ranked God Nodes (Central Connectors)",
        "",
    ])

    if top_god_nodes:
        lines.extend([
            "| Symbol | File | Total Degree | Lines | Cyclomatic Complexity |",
            "|---|---|---|---|---|",
        ])
        for gn in top_god_nodes:
            loc = f"`{gn['source_file']}:L{gn['line_start']}-L{gn['line_end']}`"
            lines.append(f"| `{gn['symbol']}` | {loc} | **{gn['degree']}** | {gn['line_count']} | {gn['cyclomatic_complexity']} |")
        lines.append("")
    else:
        lines.extend(["*No God nodes detected above connectivity threshold.*", ""])

    lines.extend([
        "### Prioritized Unit Test Targets (Ranked Business Logic)",
        "",
        "Top target functions ranked by topological centrality and cyclomatic branching complexity (recommended for Unit Testing):",
        "",
        "| Symbol | File | Lines | Cyclomatic Complexity | In-Degree (Callers) | Out-Degree (Callees) | Target Score |",
        "|---|---|---|---|---|---|---|",
    ])

    if unit_targets:
        for ut in unit_targets:
            loc = f"`{ut['source_file']}:L{ut['line_start']}-L{ut['line_end']}`"
            lines.append(f"| `{ut['symbol']}` | {loc} | {ut['line_count']} | **{ut['cyclomatic_complexity']}** | {ut['in_degree']} | {ut['out_degree']} | `{ut['score']:.1f}` |")
        lines.append("")
    else:
        lines.extend(["*No non-trivial functions identified.*", ""])

    lines.extend([
        "---",
        "",
        "## 4. Filtered Trivial Functions (Skipped Getters & Wrappers)",
        "",
        f"Identified **{len(trivial_functions)}** trivial functions (`cyclomatic_complexity <= 1` and `< 6` lines) that are intentionally filtered out of Unit Testing plans to avoid shallow assertions:",
        "",
    ])

    if trivial_functions:
        lines.extend([
            "| Function | File | Line Count | Classification |",
            "|---|---|---|---|",
        ])
        for tf in trivial_functions[:10]:
            lines.append(f"| `{tf['symbol']}` | `{tf['file']}` | {tf['lines']} | Trivial getter / passthrough |")
        if len(trivial_functions) > 10:
            lines.append(f"| *... and {len(trivial_functions) - 10} more* | | | |")
        lines.append("")
    else:
        lines.extend(["*No trivial functions found.*", ""])

    lines.extend([
        "---",
        "",
        "## 5. Architectural Health & Cycle Analysis",
        "",
    ])

    if cycles:
        lines.append(f"> [!WARNING]\n> **{len(cycles)} Circular Import Cycle(s) Detected:**\n")
        for idx, c in enumerate(cycles, 1):
            lines.append(f"{idx}. {c['description']} (length: {c['length']})")
        lines.append("")
    else:
        lines.extend([
            "> [!NOTE]\n> **Zero circular import cycles detected.** The module dependency graph is a clean Directed Acyclic Graph (DAG) at the file level.",
            "",
        ])

    content = "\n".join(lines)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")

    return content

def to_html(G: nx.DiGraph, output_path: str | Path) -> str:
    """
    Renders an interactive force-directed HTML graph with directional arrows,
    clustering physics, zoom/pan, a symbol inspector, and a legend.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    nodes_data: list[dict[str, Any]] = []
    for n, attrs in G.nodes(data=True):
        # Hide empty __init__.py files from cluttering the visual
        if attrs.get("label", "").endswith("__init__.py"):
            continue

        nodes_data.append({
            "id": n,
            "label": attrs.get("label", n),
            "type": attrs.get("node_type", "function"),
            "file": attrs.get("source_file", ""),
            "complexity": attrs.get("cyclomatic_complexity", 1),
            "is_entry": attrs.get("is_entry_point", False),
            "lines": f"L{attrs.get('line_start', 0)}-L{attrs.get('line_end', 0)}",
        })

    node_ids = {n["id"] for n in nodes_data}
    links_data: list[dict[str, Any]] = []
    for u, v, attrs in G.edges(data=True):
        if u in node_ids and v in node_ids:
            links_data.append({
                "source": u,
                "target": v,
                "relation": attrs.get("relation", ""),
                "confidence": attrs.get("confidence", "EXTRACTED"),
            })

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>TestPulse Knowledge Graph</title>
  <script src="https://d3js.org/d3.v7.min.js"></script>
  <!-- Modern clean font -->
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    body {{ margin: 0; background: #0b0f19; color: #f8fafc; font-family: 'Inter', system-ui, sans-serif; overflow: hidden; }}
    #header {{ 
      position: absolute; 
      top: 24px; 
      left: 50%; 
      transform: translateX(-50%); 
      z-index: 10; 
      pointer-events: none;
      text-align: center;
      background: rgba(15, 23, 42, 0.75);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(51, 65, 85, 0.8);
      border-radius: 16px;
      padding: 16px 32px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    }}
    #header h1 {{ 
      margin: 0; 
      font-size: 1.6rem; 
      font-weight: 700; 
      letter-spacing: -0.02em; 
      /* Modern text gradient */
      background: linear-gradient(135deg, #38bdf8, #a855f7);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    #header p {{ 
      margin: 6px 0 0 0; 
      font-size: 0.85rem; 
      color: #94a3b8; 
      font-weight: 500;
      letter-spacing: 0.01em;
    }}
    
    /* Shared glassmorphism styling for floating panels */
    .glass-panel {{
      position: absolute; background: rgba(15, 23, 42, 0.85);
      border: 1px solid #334155; border-radius: 8px; padding: 14px; font-size: 0.82rem; 
      backdrop-filter: blur(8px); box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    }}
    
    /* Node Inspector Panel */
    #panel {{ bottom: 20px; right: 20px; width: 280px; display: none; }}
    #panel h3 {{ margin: 0 0 6px 0; font-size: 0.95rem; color: #38bdf8; }}
    .badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.72rem; font-weight: bold; margin-bottom: 8px; }}
    
    /* Legend Panel */
    #legend {{ bottom: 20px; left: 20px; width: 220px; pointer-events: none; }}
    #legend h3 {{ margin: 0 0 10px 0; font-size: 0.9rem; color: #f8fafc; font-weight: 600; }}
    .leg-row {{ display: flex; align-items: center; margin-bottom: 8px; color: #cbd5e1; }}
    .leg-dot {{ width: 12px; height: 12px; border-radius: 50%; margin-right: 10px; flex-shrink: 0; }}
    .leg-line {{ width: 16px; height: 2px; margin-right: 8px; flex-shrink: 0; }}
    .leg-ext {{ background: #475569; }}
    .leg-inf {{ border-top: 2px dashed #38bdf8; background: transparent; height: 0; }}
    
    svg {{ width: 100vw; height: 100vh; cursor: grab; }}
    svg:active {{ cursor: grabbing; }}
    .link-extracted {{ stroke: #475569; stroke-width: 1.5px; stroke-opacity: 0.7; }}
    .link-inferred {{ stroke: #38bdf8; stroke-width: 2px; stroke-dasharray: 4,3; stroke-opacity: 0.9; }}
    .node text {{ font-size: 11px; fill: #94a3b8; pointer-events: none; transition: fill 0.2s; }}
    .node:hover text {{ fill: #f8fafc; font-weight: bold; font-size: 12px; }}
  </style>
</head>
<body>
  <div id="header">
    <h1>TestPulse Structural Knowledge Graph</h1>
    <p>Nodes: {len(nodes_data)} | Edges: {len(links_data)} &bull; Scroll to Zoom, Drag to Move, Click to Inspect</p>
  </div>
  
  <div id="legend" class="glass-panel">
    <h3>Legend</h3>
    <div class="leg-row"><div class="leg-dot" style="background: #f43f5e;"></div>FastAPI Entry Point</div>
    <div class="leg-row"><div class="leg-dot" style="background: #38bdf8;"></div>File Module</div>
    <div class="leg-row"><div class="leg-dot" style="background: #a855f7;"></div>Class / Model</div>
    <div class="leg-row"><div class="leg-dot" style="background: #10b981;"></div>Function / Method</div>
    <div style="height: 6px;"></div>
    <div class="leg-row"><div class="leg-line leg-ext"></div>Explicit (Import / Contain)</div>
    <div class="leg-row"><div class="leg-line leg-inf"></div>Inferred (Function Call)</div>
  </div>

  <div id="panel" class="glass-panel">
    <h3 id="p-label">-</h3>
    <div id="p-badge" class="badge"></div>
    <div><strong>File:</strong> <span id="p-file" style="color:#cbd5e1">-</span></div>
    <div><strong>Lines:</strong> <span id="p-lines" style="color:#cbd5e1">-</span></div>
    <div><strong>Complexity:</strong> <span id="p-complexity" style="color:#cbd5e1">-</span></div>
  </div>
  
  <svg id="viz"></svg>
  
  <script>
    const data = {{
      nodes: {json.dumps(nodes_data)},
      links: {json.dumps(links_data)}
    }};

    const svg = d3.select('#viz');
    const width = window.innerWidth;
    const height = window.innerHeight;
    const g = svg.append('g');

    svg.call(d3.zoom().scaleExtent([0.2, 4]).on('zoom', (e) => g.attr('transform', e.transform)));

    svg.append('defs').selectAll('marker')
      .data(['extracted', 'inferred'])
      .enter().append('marker')
      .attr('id', d => 'arrow-' + d)
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', d => d === 'inferred' ? '#38bdf8' : '#64748b');

    const sim = d3.forceSimulation(data.nodes)
      .force('link', d3.forceLink(data.links).id(d => d.id).distance(100))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(d => 16 + d.complexity * 2));

    const link = g.append('g')
      .selectAll('line')
      .data(data.links)
      .enter().append('line')
      .attr('class', d => d.confidence === 'INFERRED' ? 'link-inferred' : 'link-extracted')
      .attr('marker-end', d => 'url(#arrow-' + d.confidence.toLowerCase() + ')');

    const node = g.append('g')
      .selectAll('g')
      .data(data.nodes)
      .enter().append('g')
      .attr('class', 'node')
      .call(d3.drag()
        .on('start', (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
        .on('drag', (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
        .on('end', (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}))
      .on('click', (e, d) => {{
        const p = document.getElementById('panel');
        p.style.display = 'block';
        document.getElementById('p-label').innerText = d.label;
        document.getElementById('p-file').innerText = d.file;
        document.getElementById('p-lines').innerText = d.lines;
        document.getElementById('p-complexity').innerText = d.complexity;
        const b = document.getElementById('p-badge');
        b.innerText = d.is_entry ? 'FASTAPI ENTRY POINT' : d.type.toUpperCase();
        b.style.background = d.is_entry ? '#f43f5e' : (d.type === 'file' ? '#38bdf8' : (d.type === 'class' ? '#a855f7' : '#10b981'));
        b.style.color = '#000';
      }});

    node.append('circle')
      .attr('r', d => d.is_entry ? 10 : (d.type === 'file' ? 8 : 5 + Math.min(d.complexity, 10)))
      .attr('fill', d => d.is_entry ? '#f43f5e' : (d.type === 'file' ? '#38bdf8' : (d.type === 'class' ? '#a855f7' : '#10b981')))
      .attr('stroke', '#1e293b')
      .attr('stroke-width', 2);

    node.append('text')
      .attr('x', 14)
      .attr('y', 4)
      .text(d => d.label);

    sim.on('tick', () => {{
      link
        .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
    }});
  </script>
</body>
</html>"""
    out.write_text(html_content, encoding="utf-8")
    return str(out)