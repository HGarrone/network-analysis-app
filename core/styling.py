"""
styling.py
Assegna attributi visivi ai nodi e agli edge, in modo che siano poi
esportabili verso Gephi/Cytoscape/HTML/PNG (le funzioni di export in
export.py leggono gli attributi 'viz_color', 'viz_size', 'viz_shape').

Concetto chiave richiesto dall'utente: colore e sfumatura devono essere
SOVRAPPONIBILI, cioè:
  - l'HUE (tonalità) codifica una variabile categoriale (es. Category)
  - la LUMINOSITA'/SATURAZIONE (sfumatura) codifica una variabile continua
    (es. Importo totale, Anno) mantenendo la stessa tonalità di base
Così un nodo resta riconoscibile come "della categoria X" anche quando la
sfumatura cambia in base al valore continuo.
"""

from __future__ import annotations

import colorsys
import json
from pathlib import Path

import networkx as nx

from .config import BASE_HUE_PALETTE

# Palette qualitative selezionabili (stile "Palette" di Gephi). "Default" è
# la BASE_HUE_PALETTE di config.py (pensata per il dataset del progetto);
# le altre sono palette qualitative standard, buone su sfondo chiaro/scuro.
PALETTES: dict[str, list[str]] = {
    "Default": BASE_HUE_PALETTE,
    "Tableau 10": ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
                   "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"],
    "Set2 (pastello)": ["#66C2A5", "#FC8D62", "#8DA0CB", "#E78AC3", "#A6D854",
                         "#FFD92F", "#E5C494", "#B3B3B3"],
    "Scala di grigi (stampa)": ["#1A1A1A", "#4D4D4D", "#767676", "#999999",
                                 "#B3B3B3", "#333333", "#5C5C5C", "#828282"],
}
DEFAULT_PALETTE_NAME = "Default"

# Palette create dall'utente nella GUI (editor "Crea la tua palette"): salvate
# in un JSON accanto all'app, così restano disponibili anche ai riavvii.
CUSTOM_PALETTES_FILE = Path(__file__).resolve().parent.parent / "custom_palettes.json"


def load_custom_palettes() -> dict[str, list[str]]:
    try:
        data = json.loads(CUSTOM_PALETTES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): [str(c) for c in v] for k, v in data.items()
            if isinstance(v, list) and len(v) >= 2}


def save_custom_palettes(palettes: dict[str, list[str]]) -> None:
    CUSTOM_PALETTES_FILE.write_text(json.dumps(palettes, indent=2, ensure_ascii=False),
                                     encoding="utf-8")


def all_palettes() -> dict[str, list[str]]:
    """Palette personalizzate (in cima) + quelle predefinite."""
    return {**load_custom_palettes(), **PALETTES}


# ---------------------------------------------------------------------------
# Colore: hue per categoria + shade per variabile continua
# ---------------------------------------------------------------------------

def _hex_to_hls(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)


def _hls_to_hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def build_category_palette(categories: list, palette_colors: list[str] | None = None) -> dict:
    """Assegna una hue di base (colore pieno, luminosità 0.5) a ogni categoria
    distinta, pescando da palette_colors (default: PALETTES[DEFAULT_PALETTE_NAME])."""
    colors = palette_colors or PALETTES[DEFAULT_PALETTE_NAME]
    categories = sorted({c for c in categories if c is not None}, key=str)
    palette = {}
    for i, cat in enumerate(categories):
        palette[cat] = colors[i % len(colors)]
    return palette


def shade_color(base_hex: str, value: float, vmin: float, vmax: float,
                 l_range: tuple[float, float] = (0.30, 0.80)) -> str:
    """
    Applica una sfumatura alla hue di base in base a un valore continuo
    normalizzato tra vmin e vmax: valore basso -> più scuro, valore alto -> più chiaro
    (o viceversa, invertendo l_range). La hue resta invariata, cambia solo L.
    """
    h, _, s = _hex_to_hls(base_hex)
    if vmax == vmin:
        norm = 0.5
    else:
        norm = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
    l = l_range[0] + norm * (l_range[1] - l_range[0])
    s = max(s, 0.35)  # mantiene un minimo di saturazione anche se il base_hex è grigiastro
    return _hls_to_hex(h, l, s)


def color_by_category_and_intensity(
    G: nx.Graph,
    category_attr: str = "category",
    intensity_attr: str | None = None,
    palette: dict | None = None,
    palette_colors: list[str] | None = None,
) -> dict:
    """
    Ritorna {nodo: colore_hex}.
    - Se intensity_attr è None: colore pieno della categoria.
    - Se intensity_attr è specificato (es. 'importo_totale', o un attributo
      numerico su nodo tipo 'anno_max'): sfumatura della hue di categoria in
      base al valore normalizzato di quell'attributo su tutti i nodi.
    palette_colors: lista di colori hex da cui pescare (es. PALETTES["Tableau 10"]);
    ignorata se palette (mappa già pronta categoria->colore) è data.
    """
    cats = [G.nodes[n].get(category_attr) for n in G.nodes()]
    palette = palette or build_category_palette(cats, palette_colors=palette_colors)

    if intensity_attr is None:
        return {n: palette.get(G.nodes[n].get(category_attr), "#999999") for n in G.nodes()}

    values = [G.nodes[n].get(intensity_attr) for n in G.nodes()
              if isinstance(G.nodes[n].get(intensity_attr), (int, float))]
    vmin, vmax = (min(values), max(values)) if values else (0, 1)

    colors = {}
    for n in G.nodes():
        base = palette.get(G.nodes[n].get(category_attr), "#999999")
        val = G.nodes[n].get(intensity_attr)
        if isinstance(val, (int, float)):
            colors[n] = shade_color(base, val, vmin, vmax)
        else:
            colors[n] = base
    return colors


# ---------------------------------------------------------------------------
# Dimensione nodo (mappata linearmente/log su un attributo, es. degree o importo)
# ---------------------------------------------------------------------------

def size_by_attribute(G: nx.Graph, attr: str, size_range: tuple[float, float] = (8, 40),
                       log_scale: bool = False) -> dict:
    import math
    values = {n: G.nodes[n].get(attr, 0) or 0 for n in G.nodes()}
    nums = list(values.values())
    if not nums:
        return {}
    vmin, vmax = min(nums), max(nums)
    sizes = {}
    for n, v in values.items():
        vv = math.log1p(v) if log_scale else v
        vvmin = math.log1p(vmin) if log_scale else vmin
        vvmax = math.log1p(vmax) if log_scale else vmax
        norm = 0.5 if vvmax == vvmin else (vv - vvmin) / (vvmax - vvmin)
        sizes[n] = size_range[0] + norm * (size_range[1] - size_range[0])
    return sizes


# ---------------------------------------------------------------------------
# Forma nodo (mappatura categoriale -> forme supportate da Gephi/pyvis/matplotlib)
# ---------------------------------------------------------------------------

# Forme compatibili con pyvis/vis.js (usate per l'export HTML interattivo)
PYVIS_SHAPES = ["dot", "square", "triangle", "diamond", "star", "hexagon", "triangleDown"]
# Marker compatibili con matplotlib (per l'export PNG), stesso ordine di PYVIS_SHAPES
MPL_SHAPES = ["o", "s", "^", "D", "*", "h", "v"]
PYVIS_TO_MPL = dict(zip(PYVIS_SHAPES, MPL_SHAPES))
# Nomi leggibili per i menu della GUI
SHAPE_LABELS = {"dot": "● Cerchio", "square": "■ Quadrato", "triangle": "▲ Triangolo",
                "diamond": "◆ Rombo", "star": "★ Stella", "hexagon": "⬢ Esagono",
                "triangleDown": "▼ Triangolo giù"}


def shape_by_attribute(G: nx.Graph, attr: str, target: str = "pyvis",
                       shape_map: dict | None = None) -> dict:
    """
    Mappa i valori distinti di un attributo categoriale (tipicamente 'type' o
    'bipartite': ente/progetto) su forme diverse.
    target: 'pyvis' oppure 'matplotlib'.
    shape_map: {valore (come stringa): forma pyvis} scelto a mano dall'utente;
    i valori non presenti ricevono le forme in ordine, come prima.
    """
    shapes = PYVIS_SHAPES if target == "pyvis" else MPL_SHAPES
    values = sorted({G.nodes[n].get(attr) for n in G.nodes() if G.nodes[n].get(attr) is not None}, key=str)
    mapping = {v: shapes[i % len(shapes)] for i, v in enumerate(values)}
    for v in values:
        chosen = (shape_map or {}).get(str(v))
        if chosen in PYVIS_TO_MPL:
            mapping[v] = chosen if target == "pyvis" else PYVIS_TO_MPL[chosen]
    return {n: mapping.get(G.nodes[n].get(attr), shapes[0]) for n in G.nodes()}


# ---------------------------------------------------------------------------
# Stile degli EDGE (colore per attributo — es. layer/interaction_type — e
# spessore per peso). Scrive 'viz_edge_color' e 'viz_width' sugli edge.
# ---------------------------------------------------------------------------

EDGE_DEFAULT_COLOR = "#888888"


def _edge_data_iter(G):
    """Itera i dict-dati degli edge in modo uniforme (Graph e MultiGraph):
    mutare il dict restituito scrive direttamente sull'edge."""
    if G.is_multigraph():
        return (d for _, _, _, d in G.edges(keys=True, data=True))
    return (d for _, _, d in G.edges(data=True))


def apply_edge_style(
    G: nx.Graph,
    color_by: str | None = None,
    width_by: str | None = "weight",
    width_range: tuple[float, float] = (1, 9),
    palette: dict | None = None,
    palette_colors: list[str] | None = None,
) -> nx.Graph:
    """
    Stile degli edge (in place, ritorna G):
    - color_by: attributo categoriale dell'edge (es. 'layer' per il multiplex
      composto, 'interaction_type', 'anno') -> 'viz_edge_color' con la stessa
      palette per-categoria dei nodi (passarne una per coordinare i colori).
    - width_by: attributo numerico (default 'weight') -> 'viz_width'
      normalizzato in width_range.
    Funziona anche sui MultiGraph (ogni edge parallelo ha il suo stile).
    """
    if color_by:
        values = [d.get(color_by) for d in _edge_data_iter(G)]
        palette = palette or build_category_palette(values, palette_colors=palette_colors)
        for d in _edge_data_iter(G):
            d["viz_edge_color"] = palette.get(d.get(color_by), EDGE_DEFAULT_COLOR)

    if width_by:
        weights = [d.get(width_by, 1) or 1 for d in _edge_data_iter(G)]
        if weights:
            wmin, wmax = min(weights), max(weights)
            for d in _edge_data_iter(G):
                w = d.get(width_by, 1) or 1
                norm = 0.5 if wmax == wmin else (w - wmin) / (wmax - wmin)
                d["viz_width"] = width_range[0] + norm * (width_range[1] - width_range[0])
    return G


# ---------------------------------------------------------------------------
# Stile di linea degli EDGE (solid/dashed/dotted/double — vocabolario nativo
# GEXF/Gephi; 'double' e i tratteggi sono simulati sugli altri renderer, vedi
# export.py). Scrive 'viz_edge_dash' sugli edge.
# ---------------------------------------------------------------------------

EDGE_DASH_STYLES = ["solid", "dashed", "dotted", "double"]


def apply_edge_dash(G: nx.Graph, dash_by: str | None = None) -> nx.Graph:
    """
    Assegna uno stile di linea per valore distinto di un attributo edge
    categoriale (ciclando su EDGE_DASH_STYLES), utile per distinguere
    visivamente i layer/tipi di legame anche in stampa B/N. Senza dash_by,
    tutti gli edge restano 'solid'.
    """
    if not dash_by:
        for d in _edge_data_iter(G):
            d.setdefault("viz_edge_dash", "solid")
        return G
    values = sorted({str(d.get(dash_by)) for d in _edge_data_iter(G) if d.get(dash_by) is not None})
    mapping = {v: EDGE_DASH_STYLES[i % len(EDGE_DASH_STYLES)] for i, v in enumerate(values)}
    for d in _edge_data_iter(G):
        d["viz_edge_dash"] = mapping.get(str(d.get(dash_by)), "solid")
    return G


# ---------------------------------------------------------------------------
# Applica tutto lo stile al grafo (scrive attributi viz_* sui nodi/edge)
# ---------------------------------------------------------------------------

def apply_style(
    G: nx.Graph,
    color_by: str | None = "category",
    shade_by: str | None = None,
    size_by: str | None = None,
    shape_by: str | None = "bipartite",
    size_range: tuple[float, float] = (8, 40),
    size_log_scale: bool = False,
    shape_target: str = "pyvis",
    edge_color_by: str | None = None,
    edge_dash_by: str | None = None,
    palette_colors: list[str] | None = None,
    shape_map: dict | None = None,
) -> nx.Graph:
    """
    Unico punto d'ingresso dello stile: scrive 'viz_color', 'viz_size',
    'viz_shape' sui nodi e 'viz_edge_color', 'viz_width', 'viz_edge_dash'
    sugli edge (in place, ritorna G). Tutti i renderer (export_png,
    export_html, finestra interattiva, GEXF) leggono questi attributi: una
    nuova impostazione di stile aggiunta qui si applica automaticamente
    ovunque.
    edge_color_by: attributo dell'edge per colorarli (es. 'layer',
    'interaction_type', 'anno') — vedi apply_edge_style.
    edge_dash_by: attributo dell'edge per lo stile di linea (solid/dashed/
    dotted/double) — vedi apply_edge_dash.
    palette_colors: lista di colori hex (es. PALETTES["Tableau 10"]) per
    hue nodi ED edge, così restano coordinati.
    shape_map: forma scelta a mano per ciascun valore di shape_by (vedi
    shape_by_attribute).
    """
    colors = (color_by_category_and_intensity(G, color_by, shade_by, palette_colors=palette_colors)
              if color_by else {n: "#999999" for n in G.nodes()})
    sizes = size_by_attribute(G, size_by, size_range, size_log_scale) if size_by else {n: 15 for n in G.nodes()}
    shapes = (shape_by_attribute(G, shape_by, shape_target, shape_map=shape_map)
              if shape_by else {n: PYVIS_SHAPES[0] for n in G.nodes()})

    for n in G.nodes():
        G.nodes[n]["viz_color"] = colors.get(n, "#999999")
        G.nodes[n]["viz_size"] = sizes.get(n, 15)
        G.nodes[n]["viz_shape"] = shapes.get(n, PYVIS_SHAPES[0])

    apply_edge_style(G, color_by=edge_color_by, width_by="weight", palette_colors=palette_colors)
    return apply_edge_dash(G, dash_by=edge_dash_by)


# ---------------------------------------------------------------------------
# Scala complessiva (moltiplicatore su nodi/edge/etichette già stilizzati) e
# scelta di quale/i colonna/e mostrare come etichetta — entrambe pensate per
# rifinire l'immagine finale (PNG/SVG/HTML) senza toccare i dati originali.
# ---------------------------------------------------------------------------

DEFAULT_LABEL_SIZE = 14  # punti (matplotlib) / vis.js font size, prima della scala


def apply_scale(G: nx.Graph, node_scale: float = 1.0, edge_scale: float = 1.0,
                 label_scale: float = 1.0) -> nx.Graph:
    """
    Moltiplicatore complessivo (stile "Preview Ratio" di Gephi) su
    dimensione nodi (viz_size), spessore edge (viz_width) ed etichette
    (viz_label_size, nuovo): va applicato DOPO apply_style, che scrive i
    valori di base. In place, ritorna G.
    """
    if node_scale != 1.0:
        for n in G.nodes():
            G.nodes[n]["viz_size"] = G.nodes[n].get("viz_size", 15) * node_scale
    if edge_scale != 1.0:
        for d in _edge_data_iter(G):
            d["viz_width"] = d.get("viz_width", 1) * edge_scale
    label_size = DEFAULT_LABEL_SIZE * label_scale
    for n in G.nodes():
        G.nodes[n]["viz_label_size"] = label_size
    return G


def apply_label_override(G: nx.Graph, label_attrs: list[str] | None) -> nx.Graph:
    """
    Sovrascrive 'label' sui nodi concatenando i valori degli attributi
    scelti (separati da ' / '), SOLO per la resa visiva — usare su una copia
    del grafo, non sui dati originali. Con label_attrs vuoto/None, non tocca
    nulla (resta la label già caricata).
    """
    if not label_attrs:
        return G
    for n in G.nodes():
        parts = [str(G.nodes[n].get(a)) for a in label_attrs if G.nodes[n].get(a) is not None]
        if parts:
            G.nodes[n]["label"] = " / ".join(parts)
    return G
