"""
animation.py
Animazione dell'evoluzione temporale della rete: una sequenza di frame
(uno per anno) salvata come GIF, con opzionalmente i singoli frame PNG.

Scelte di design:
- Il LAYOUT È FISSO: le posizioni sono calcolate una volta sola sull'unione
  di tutti gli anni, così i nodi non "saltano" tra un frame e l'altro e
  l'occhio segue davvero l'evoluzione (nuovi nodi che si accendono, aree
  che si addensano), non il rumore del layout.
- I nodi non ancora/più attivi in un anno possono restare visibili come
  "fantasmi" grigi (show_inactive=True): rende leggibile cosa è entrato
  e cosa manca rispetto al totale.
- Il colore segue un attributo categoriale (default 'category') con la
  stessa palette di styling/config, costante per tutta l'animazione.

Due livelli d'uso:
- `animate_graphs({anno: grafo}, path)` — generico: accetta qualunque
  sequenza di grafi indicizzata (es. output di temporal.split_by_year o
  di projections.project_by_year).
- `animate_evolution(G_bipartite, path, mode, on)` — scorciatoia: divide
  per anno (snapshot/cumulativo) ed eventualmente proietta ogni anno sul
  lato scelto, poi anima.
"""

from __future__ import annotations

import io
import os

import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from PIL import Image

from .layout import compute_layout
from .config import BASE_HUE_PALETTE


def build_color_map(graphs: list[nx.Graph], color_by: str = "category") -> dict:
    """Mappa {valore_attributo: colore} costante su tutti i frame."""
    values = set()
    for g in graphs:
        values.update(str(g.nodes[n].get(color_by)) for n in g.nodes()
                      if g.nodes[n].get(color_by) is not None)
    return {v: BASE_HUE_PALETTE[i % len(BASE_HUE_PALETTE)]
            for i, v in enumerate(sorted(values))}


def _render_frame(U: nx.Graph, G_year: nx.Graph, pos: dict, color_map: dict,
                   color_by: str, frame_title: str, figsize: tuple, dpi: int,
                   show_inactive: bool, node_size: float) -> Image.Image:
    """Disegna un singolo frame e lo ritorna come immagine PIL."""
    fig, ax = plt.subplots(figsize=figsize)

    inactive = [n for n in U.nodes() if n not in G_year]
    if show_inactive and inactive:
        nx.draw_networkx_nodes(U, pos, nodelist=inactive, ax=ax, node_size=node_size * 0.4,
                                node_color="#dddddd", linewidths=0)

    active = [n for n in G_year.nodes()]
    colors = [color_map.get(str(G_year.nodes[n].get(color_by)), "#999999") for n in active]
    widths = [d.get("viz_width", 1) for _, _, d in G_year.edges(data=True)]
    nx.draw_networkx_edges(G_year, pos, ax=ax, width=widths, alpha=0.3, edge_color="#888888")
    nx.draw_networkx_nodes(G_year, pos, nodelist=active, ax=ax, node_size=node_size,
                            node_color=colors, linewidths=0.5, edgecolors="white")

    if color_map and len(color_map) <= 12:
        handles = [Line2D([], [], marker="o", linestyle="", color=c, label=v)
                   for v, c in color_map.items()]
        ax.legend(handles=handles, loc="lower left", fontsize=7, frameon=False)

    ax.set_title(frame_title, fontsize=12)
    ax.axis("off")
    # niente bbox_inches='tight': i frame di una GIF devono avere tutti la stessa dimensione
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def animate_graphs(graphs_by_year: dict, path: str, pos: dict | None = None,
                    layout_method: str = "spring", color_by: str = "category",
                    fps: float = 1.0, figsize: tuple = (10, 10), dpi: int = 100,
                    show_inactive: bool = True, node_size: float = 60,
                    title: str = "Evoluzione della rete",
                    frames_dir: str | None = None) -> str:
    """
    Salva una GIF animata da {anno: grafo}. Il layout è calcolato una volta
    sull'unione di tutti i grafi (o passato esplicitamente con pos, es. per
    riusare quello di un'altra visualizzazione). fps = frame al secondo;
    l'ultimo frame resta visibile il triplo del tempo prima di ripartire.
    Con frames_dir, salva anche i singoli frame come PNG numerati
    (utile per montaggi video esterni).
    """
    if not graphs_by_year:
        raise ValueError("Nessun grafo da animare: graphs_by_year è vuoto.")
    years = sorted(graphs_by_year)
    U = nx.compose_all([graphs_by_year[y] for y in years])
    if pos is None:
        pos = compute_layout(U, method=layout_method)
    color_map = build_color_map([graphs_by_year[y] for y in years], color_by)

    frames = []
    for y in years:
        g = graphs_by_year[y]
        frame_title = f"{title} — {y}   ({g.number_of_nodes()} nodi, {g.number_of_edges()} legami)"
        frames.append(_render_frame(U, g, pos, color_map, color_by, frame_title,
                                     figsize, dpi, show_inactive, node_size))

    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
        for y, img in zip(years, frames):
            img.save(os.path.join(frames_dir, f"frame_{y}.png"))

    base_ms = int(1000 / fps)
    durations = [base_ms] * len(frames)
    durations[-1] = base_ms * 3  # pausa sull'ultimo frame prima del loop
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, optimize=True)
    return path


def animate_evolution(G: nx.Graph, path: str, mode: str = "cumulative",
                       on: str | None = None, weight_mode: str = "count",
                       year_attr: str = "anno", **kwargs) -> str:
    """
    Scorciatoia: anima l'evoluzione del grafo bipartito (che porta l'anno
    sugli edge). mode: 'snapshot' o 'cumulative'. Con on='ente'/'progetto'
    anima la proiezione per anno invece del bipartito. kwargs passati a
    animate_graphs (fps, color_by, show_inactive, frames_dir, ...).
    """
    from . import temporal, projections  # import locale per evitare cicli

    if on is None:
        graphs_by_year = temporal.split_by_year(G, mode=mode, year_attr=year_attr)
        default_title = f"Evoluzione rete bipartita ({mode})"
    else:
        graphs_by_year = projections.project_by_year(G, on=on, weight_mode=weight_mode,
                                                      mode=mode, year_attr=year_attr)
        default_title = f"Evoluzione proiezione {on} ({mode})"
    kwargs.setdefault("title", default_title)
    return animate_graphs(graphs_by_year, path, **kwargs)
