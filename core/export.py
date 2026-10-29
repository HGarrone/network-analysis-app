"""
export.py
Esportazione della rete verso i formati richiesti:
  - GEXF    -> Gephi (formato nativo, supporta colori/dimensioni/dinamiche temporali)
  - GraphML -> Cytoscape / Gephi (formato generico più universale)
  - CSV (node table + edge table) -> Cytoscape (import via "Import Table",
    più flessibile del GraphML per definire lo stile direttamente in Cytoscape)
  - PNG     -> immagine statica (matplotlib)
  - HTML    -> rete interattiva (pyvis / vis.js), utile da allegare al report

NOTA formati: GEXF e GraphML non supportano attributi con valore None/liste
python native in modo affidabile: le funzioni qui sotto fanno una pulizia
("sanitize") prima di scrivere il file.
"""

from __future__ import annotations

import json
import os

import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .layout import compute_layout
from .config import NODE_COLS, EDGE_COLS
from .styling import PYVIS_TO_MPL

# mappa attributi interni -> intestazioni originali dei file Excel dell'utente
_NODE_COL_RENAME = {
    "id_originale": NODE_COLS["id"], "label": NODE_COLS["label"],
    "type": NODE_COLS["type"], "category": NODE_COLS["category"],
    "ambito": NODE_COLS["ambito"], "sotto_ambito": NODE_COLS["sotto_ambito"],
    "dettaglio": NODE_COLS["dettaglio"], "anni": NODE_COLS["anno"],
}
_EDGE_COL_RENAME = {
    "anno": EDGE_COLS["anno"], "interaction_type": EDGE_COLS["interaction_type"],
    "importo": EDGE_COLS["importo"],
}


def _sanitize_for_export(G: nx.Graph) -> nx.Graph:
    """Converte None -> stringa vuota e liste/dict -> stringa (JSON), richiesto da GEXF/GraphML."""
    H = G.copy()
    for _, attrs in H.nodes(data=True):
        for k, v in list(attrs.items()):
            if v is None:
                attrs[k] = ""
            elif isinstance(v, (list, dict, set)):
                attrs[k] = json.dumps(list(v) if isinstance(v, set) else v, ensure_ascii=False, default=str)
    for _, _, attrs in H.edges(data=True):
        for k, v in list(attrs.items()):
            if v is None:
                attrs[k] = ""
            elif isinstance(v, (list, dict, set)):
                attrs[k] = json.dumps(list(v) if isinstance(v, set) else v, ensure_ascii=False, default=str)
    return H


# forme nodo di pyvis/vis.js -> il sottoinsieme che il viz:shape di GEXF
# capisce davvero (disc/square/triangle/diamond/image): il resto degrada a disc.
_GEXF_NODE_SHAPES = {"dot": "disc", "square": "square", "triangle": "triangle",
                      "diamond": "diamond"}


def _hex_to_rgb(hex_color) -> dict:
    hex_color = str(hex_color or "#999999").lstrip("#")
    if len(hex_color) != 6:
        return {"r": 153, "g": 153, "b": 153}
    return {"r": int(hex_color[0:2], 16), "g": int(hex_color[2:4], 16), "b": int(hex_color[4:6], 16)}


def _prepare_gexf_viz(G: nx.Graph) -> nx.Graph:
    """
    networkx.write_gexf legge lo stile visivo SOLO da un dict annidato
    'viz' (color/size/shape/thickness), non dagli attributi piatti
    viz_color/viz_size/... usati dagli altri renderer (PNG/HTML): qui si
    costruisce quel dict per nodi ed edge, così l'export GEXF mostra
    davvero colori/dimensioni/forme/stile di linea in Gephi (viz:shape
    'solid'/'dashed'/'dotted'/'double' sugli edge è nativo).
    """
    H = G.copy()
    for _, attrs in H.nodes(data=True):
        viz = {}
        if "viz_color" in attrs:
            viz["color"] = _hex_to_rgb(attrs.pop("viz_color"))
        if "viz_size" in attrs:
            viz["size"] = attrs.pop("viz_size")
        if "viz_shape" in attrs:
            viz["shape"] = _GEXF_NODE_SHAPES.get(attrs.pop("viz_shape"), "disc")
        if viz:
            attrs["viz"] = viz
    for _, _, attrs in H.edges(data=True):
        viz = {}
        if "viz_edge_color" in attrs:
            viz["color"] = _hex_to_rgb(attrs.pop("viz_edge_color"))
        if "viz_width" in attrs:
            viz["thickness"] = attrs.pop("viz_width")
        if "viz_edge_dash" in attrs:
            viz["shape"] = attrs.pop("viz_edge_dash")  # solid/dashed/dotted/double: nativi GEXF
        if viz:
            attrs["viz"] = viz
    return H


def export_gexf(G: nx.Graph, path: str) -> str:
    H = _sanitize_for_export(G)
    H = _prepare_gexf_viz(H)
    nx.write_gexf(H, path)
    return path


def export_graphml(G: nx.Graph, path: str) -> str:
    H = _sanitize_for_export(G)
    nx.write_graphml(H, path)
    return path


def export_cytoscape_tables(G: nx.Graph, nodes_csv_path: str, edges_csv_path: str) -> tuple[str, str]:
    """Esporta node table + edge table in CSV, pronte per l'import in Cytoscape
    (File > Import > Network from File... usando la edge table, poi Import >
    Table from File... per la node table)."""
    node_rows = []
    for n, attrs in G.nodes(data=True):
        row = {"id": n}
        row.update(attrs)
        node_rows.append(row)
    pd.DataFrame(node_rows).to_csv(nodes_csv_path, index=False)

    edge_rows = []
    for u, v, attrs in G.edges(data=True):
        row = {"source": u, "target": v}
        row.update(attrs)
        edge_rows.append(row)
    pd.DataFrame(edge_rows).to_csv(edges_csv_path, index=False)

    return nodes_csv_path, edges_csv_path


# stile di linea 'double' non esiste in matplotlib: si disegna come due
# linee parallele leggermente scostate (vedi _draw_double_edges).
_MPL_LINESTYLE = {"solid": "solid", "dashed": "dashed", "dotted": "dotted"}


def _draw_double_edges(ax, pos, double_edges: list, offset: float = 0.012) -> None:
    for u, v, color, width in double_edges:
        (x0, y0), (x1, y1) = pos[u], pos[v]
        dx, dy = x1 - x0, y1 - y0
        length = (dx ** 2 + dy ** 2) ** 0.5 or 1.0
        px, py = -dy / length, dx / length  # versore perpendicolare
        for sign in (-1, 1):
            ax.plot([x0 + sign * offset * px, x1 + sign * offset * px],
                    [y0 + sign * offset * py, y1 + sign * offset * py],
                    color=color, linewidth=width, alpha=0.35, solid_capstyle="round", zorder=1)


def export_png(G: nx.Graph, path: str, layout_method: str = "spring",
               figsize: tuple[int, int] = (14, 14), with_labels: bool = False,
               dpi: int = 150, transparent: bool = False, positions: dict | None = None,
               **layout_kwargs) -> str:
    """Rende un'immagine statica. Usa viz_color/viz_size/viz_edge_dash se
    presenti (vedi styling.py). transparent=True: nessuno sfondo (bianco di
    default), come l'export SVG di Gephi. positions: posizioni già
    calcolate (es. dopo layout.scale_layout per espansione/contrazione) —
    se date, salta il calcolo interno del layout. layout_kwargs: parametri
    extra per compute_layout (es. level_attr/level_order per
    layout_method='livelli'), ignorati se positions è dato."""
    pos = positions if positions is not None else compute_layout(G, method=layout_method, **layout_kwargs)
    colors = [G.nodes[n].get("viz_color", "#4C72B0") for n in G.nodes()]
    sizes = [G.nodes[n].get("viz_size", 15) * 6 for n in G.nodes()]  # scala per matplotlib

    fig, ax = plt.subplots(figsize=figsize)

    simple_edges, simple_styles, simple_widths, simple_colors = [], [], [], []
    double_edges = []
    for u, v, d in G.edges(data=True):
        dash = d.get("viz_edge_dash", "solid")
        width, color = d.get("viz_width", 1), d.get("viz_edge_color", "#888888")
        if dash == "double":
            double_edges.append((u, v, color, width))
        else:
            simple_edges.append((u, v))
            simple_styles.append(_MPL_LINESTYLE.get(dash, "solid"))
            simple_widths.append(width)
            simple_colors.append(color)
    if simple_edges:
        nx.draw_networkx_edges(G, pos, ax=ax, edgelist=simple_edges, width=simple_widths,
                                alpha=0.35, edge_color=simple_colors, style=simple_styles)
    if double_edges:
        _draw_double_edges(ax, pos, double_edges)

    # Un gruppo per forma: draw_networkx_nodes accetta un solo node_shape per
    # chiamata — prima i nodi erano tutti cerchi anche con "Forma nodi per" attivo.
    by_shape: dict[str, list[int]] = {}
    for i, n in enumerate(G.nodes()):
        marker = PYVIS_TO_MPL.get(G.nodes[n].get("viz_shape", "dot"), "o")
        by_shape.setdefault(marker, []).append(i)
    nodes = list(G.nodes())
    for marker, idxs in by_shape.items():
        nx.draw_networkx_nodes(G, pos, ax=ax, nodelist=[nodes[i] for i in idxs],
                                node_color=[colors[i] for i in idxs],
                                node_size=[sizes[i] for i in idxs], node_shape=marker,
                                linewidths=0.5, edgecolors="white")
    if with_labels:
        labels = {n: G.nodes[n].get("label", n) for n in G.nodes()}
        # viz_label_size è globale (stesso valore su tutti i nodi, scritto da
        # styling.apply_scale): draw_networkx_labels accetta un solo font_size,
        # non uno per nodo.
        label_size = next((d["viz_label_size"] for _, d in G.nodes(data=True)
                            if "viz_label_size" in d), 6)
        nx.draw_networkx_labels(G, pos, labels=labels, ax=ax, font_size=label_size)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight", transparent=transparent)
    plt.close(fig)
    return path


def export_svg(G: nx.Graph, path: str, layout_method: str = "spring",
                figsize: tuple[int, int] = (14, 14), with_labels: bool = False,
                **layout_kwargs) -> str:
    """Come export_png ma in SVG (vettoriale, editabile in Illustrator/Inkscape),
    senza sfondo — come l'export SVG di Gephi. matplotlib deduce il formato
    dall'estensione del path (deve finire in .svg)."""
    return export_png(G, path, layout_method=layout_method, figsize=figsize,
                       with_labels=with_labels, transparent=True, **layout_kwargs)


# vis.js non ha un vero stile 'double': degrada a linea continua (solid).
_VISJS_DASHES = {"solid": False, "dashed": True, "dotted": [2, 4], "double": False}


def export_html(G: nx.Graph, path: str, height: str = "800px", width: str = "100%",
                notebook: bool = False) -> str:
    """Rete interattiva HTML (pyvis/vis.js): zoom, drag, tooltip su hover."""
    from pyvis.network import Network

    # NB: NON passare font_color qui — pyvis.Node lo usa per SOVRASCRIVERE
    # incondizionatamente 'font' su ogni nodo (vedi Node.__init__), quindi
    # un font_color globale a livello di Network annulla sempre qualunque
    # font per-nodo passato ad add_node (compresa la dimensione etichetta).
    net = Network(height=height, width=width, bgcolor="#ffffff",
                  notebook=notebook, cdn_resources="in_line")
    net.barnes_hut()

    for n, attrs in G.nodes(data=True):
        label = str(attrs.get("label", n))
        title_lines = [f"{k}: {v}" for k, v in attrs.items() if not k.startswith("viz_")]
        net.add_node(
            n,
            label=label,
            title="<br>".join(title_lines),
            color=attrs.get("viz_color", "#4C72B0"),
            size=attrs.get("viz_size", 15),
            shape=attrs.get("viz_shape", "dot"),
            font=f"{attrs.get('viz_label_size', 14)}px arial #343434",
        )
    for u, v, attrs in G.edges(data=True):
        # 'width' = spessore letterale in pixel (il nostro viz_width, già
        # normalizzato); 'value', usato qui erroneamente prima, fa scattare
        # la scala AUTOMATICA di vis.js sul peso grezzo, ignorando
        # viz_width e producendo edge molto più spessi del previsto.
        net.add_edge(u, v, width=attrs.get("viz_width", 1),
                     color=attrs.get("viz_edge_color", "#888888"),
                     dashes=_VISJS_DASHES.get(attrs.get("viz_edge_dash"), False),
                     title=f"weight: {attrs.get('weight', '')}")

    net.show_buttons(filter_=["physics"])
    # net.write_html() apre il file senza specificare l'encoding: su Windows
    # usa la codepage di sistema (spesso cp1252) e va in errore sui
    # caratteri non rappresentabili nell'HTML generato da vis.js/pyvis.
    # generate_html() + scrittura esplicita in UTF-8 evita il problema.
    with open(path, "w", encoding="utf-8") as f:
        f.write(net.generate_html(notebook=notebook))
    return path


def _excel_cell(v):
    """Valore pronto per una cella Excel: le liste diventano stringhe con i
    valori unici separati da ', ' (regola di eredità delle colonne originali);
    i dict (es. records) diventano JSON."""
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, (list, tuple, set)):
        out = []
        for x in v:
            s = json.dumps(x, ensure_ascii=False, default=str) if isinstance(x, dict) else str(x)
            if s not in out:
                out.append(s)
        return ", ".join(out)
    return v


def export_excel(G: nx.Graph, path: str) -> str:
    """
    Esporta la rete (anche proiettata, fusa o coarse-grained) come UN file
    .xlsx con due fogli — 'Nodi' ed 'Edges' — mantenendo le colonne
    originali dei file di partenza (ID, Label, Type, Category, Ambito/Ruolo,
    Sotto-ambito, Dettaglio, Anno, Interaction_Type, Importo, ...) più le
    colonne calcolate dalla pipeline (degree, comunita, ...). I valori
    multipli ereditati da fusioni/accorpamenti restano separati da ', '.
    Gli attributi di solo stile (viz_*) sono esclusi.
    """
    node_rows = []
    for n, attrs in G.nodes(data=True):
        row = {"node_id": n}
        row.update({k: _excel_cell(v) for k, v in attrs.items() if not k.startswith("viz_")})
        node_rows.append(row)
    df_nodes = pd.DataFrame(node_rows).rename(columns=_NODE_COL_RENAME)

    edge_rows = []
    for u, v, attrs in G.edges(data=True):
        row = {"source": u, "target": v,
               "source_label": _excel_cell(G.nodes[u].get("label", u)),
               "target_label": _excel_cell(G.nodes[v].get("label", v))}
        row.update({k: _excel_cell(w) for k, w in attrs.items() if not k.startswith("viz_")})
        edge_rows.append(row)
    df_edges = pd.DataFrame(edge_rows).rename(columns=_EDGE_COL_RENAME)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_nodes.to_excel(writer, sheet_name="Nodi", index=False)
        df_edges.to_excel(writer, sheet_name="Edges", index=False)
    return path


def build_interactive_html(G: nx.Graph, height: str = "750px",
                            physics: bool = True, solver: str = "forceAtlas2Based",
                            positions: dict | None = None, show_labels: bool = True,
                            show_config_panel: bool = True) -> str:
    """
    Rete interattiva come STRINGA HTML (vis.js), pensata per essere
    incorporata nella GUI (st.components.html) come finestra di lavoro:
    zoom, drag dei nodi, tooltip, fisica live regolabile da pannello.

    - solver (fisica live): 'forceAtlas2Based' (equivalente interattivo di
      ForceAtlas2), 'barnesHut', 'repulsion'.
    - positions: {nodo: (x, y)} da layout.compute_layout per partire da
      posizioni precalcolate (spring/kamada_kawai/fa2); con physics=False
      le posizioni restano fisse ma i nodi sono comunque trascinabili.
    - show_config_panel: pannello vis.js con gli slider della fisica
      (gravità, molla, smorzamento...), stile pannello layout di Gephi.
    NB: Yifan Hu non esiste in vis.js/networkx: per quello esportare il
    GEXF e usare Gephi.
    Usa viz_color/viz_size/viz_shape se presenti (vedi styling.py).
    """
    from pyvis.network import Network

    # NB: NON passare font_color qui — pyvis.Node lo userebbe per
    # sovrascrivere incondizionatamente 'font' su ogni nodo, annullando
    # la dimensione etichetta per-nodo passata più sotto (viz_label_size).
    net = Network(height=height, width="100%", bgcolor="#ffffff",
                  notebook=False, cdn_resources="in_line")
    scale = 600  # i layout networkx vivono in ~[-1,1]: riscala per vis.js

    for n, attrs in G.nodes(data=True):
        kwargs = dict(
            label=str(attrs.get("label", n)) if show_labels else " ",
            title="<br>".join(f"{k}: {v}" for k, v in attrs.items() if not k.startswith("viz_")),
            color=attrs.get("viz_color", "#4C72B0"),
            size=attrs.get("viz_size", 12),
            shape=attrs.get("viz_shape", "dot"),
            font=f"{attrs.get('viz_label_size', 14)}px arial #343434",
        )
        if positions is not None and n in positions:
            x, y = positions[n]
            kwargs.update(x=float(x) * scale, y=float(y) * scale)
        net.add_node(n, **kwargs)
    for u, v, attrs in G.edges(data=True):
        # width = spessore letterale (viz_width, già normalizzato), non
        # 'value' (che fa scattare la scala automatica di vis.js sul peso
        # grezzo, ignorando la nostra normalizzazione/scala complessiva).
        net.add_edge(u, v, width=attrs.get("viz_width", 1),
                     color=attrs.get("viz_edge_color", "#888888"),
                     dashes=_VISJS_DASHES.get(attrs.get("viz_edge_dash"), False),
                     title=f"weight: {attrs.get('weight', '')}"
                           + (f"<br>layer: {attrs['layer']}" if "layer" in attrs else ""))

    if not physics:
        net.toggle_physics(False)
    elif solver == "barnesHut":
        net.barnes_hut()
    elif solver == "repulsion":
        net.repulsion()
    else:
        net.force_atlas_2based()
    try:  # opzioni di interazione non critiche: non bloccare se pyvis cambia API
        net.options.interaction.hover = True
        net.options.interaction.navigationButtons = True
    except Exception:
        pass
    if show_config_panel:
        net.show_buttons(filter_=["physics"])
    return net.generate_html()


def export_all(G: nx.Graph, out_dir: str, basename: str, positions: dict | None = None) -> dict:
    """Comodo per la GUI/pipeline: esporta in tutti i formati in un colpo solo.
    positions: posizioni già calcolate (es. quelle della vista live) per
    PNG/SVG coerenti con quanto mostrato in GUI, invece di ricalcolarle da zero."""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    paths["gexf"] = export_gexf(G, os.path.join(out_dir, f"{basename}.gexf"))
    paths["graphml"] = export_graphml(G, os.path.join(out_dir, f"{basename}.graphml"))
    paths["cytoscape_nodes_csv"], paths["cytoscape_edges_csv"] = export_cytoscape_tables(
        G, os.path.join(out_dir, f"{basename}_nodes.csv"), os.path.join(out_dir, f"{basename}_edges.csv")
    )
    paths["png"] = export_png(G, os.path.join(out_dir, f"{basename}.png"), positions=positions)
    paths["svg"] = export_svg(G, os.path.join(out_dir, f"{basename}.svg"), positions=positions)
    paths["html"] = export_html(G, os.path.join(out_dir, f"{basename}.html"))
    paths["xlsx"] = export_excel(G, os.path.join(out_dir, f"{basename}.xlsx"))
    return paths
