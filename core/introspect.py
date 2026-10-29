"""
introspect.py
Scopre dinamicamente quali attributi (di nodo e di edge) sono presenti
sulla rete ATTIVA, distinguendo numerici (gradienti di colore/dimensione)
da categoriali/testuali (forme, colori a tinte piene, raggruppamenti).

Sostituisce le liste di attributi fisse ("category", "ambito", ...) cucite
sul dataset di un progetto specifico: qualunque rete (importata da Gephi/R,
caricata da tabelle generiche, o il bipartito di un progetto con le sue
colonne) espone così nella GUI solo gli attributi che possiede DAVVERO.
"""

from __future__ import annotations

import networkx as nx

# attributi interni/di bookkeeping da non proporre come "categorizzabili":
# non descrivono il nodo/edge in modo utile per uno stile o un raggruppamento,
# sono identificatori o strutture dati interne della pipeline (fusioni nodi,
# multi-relazioni accorpate, stile già applicato...).
_SKIP_KEYS = {"label", "id_originale", "membri", "membri_labels", "n_membri",
              "records", "n_archi_uniti"}


def _is_numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _classify(values_by_key: dict[str, list]) -> tuple[list[str], list[str]]:
    numeric, categorical = [], []
    for key, values in values_by_key.items():
        if key in _SKIP_KEYS or key.startswith("viz_"):
            continue
        non_null = [v for v in values if v is not None and v != ""]
        if not non_null:
            continue
        if any(isinstance(v, (list, dict, set)) for v in non_null):
            continue  # non stilizzabile (es. liste di anni, record multipli)
        if all(_is_numeric(v) for v in non_null):
            numeric.append(key)
        else:
            categorical.append(key)
    return sorted(numeric), sorted(categorical)


def graph_attributes(G: nx.Graph) -> dict:
    """
    Ritorna {"node_numeric": [...], "node_categorical": [...],
             "edge_numeric": [...], "edge_categorical": [...]}
    scansionando i valori REALI presenti sul grafo attivo.
    """
    node_values: dict[str, list] = {}
    for _, attrs in G.nodes(data=True):
        for k, v in attrs.items():
            node_values.setdefault(k, []).append(v)

    edge_values: dict[str, list] = {}
    for _, _, attrs in G.edges(data=True):
        for k, v in attrs.items():
            edge_values.setdefault(k, []).append(v)

    node_numeric, node_categorical = _classify(node_values)
    edge_numeric, edge_categorical = _classify(edge_values)
    return {
        "node_numeric": node_numeric,
        "node_categorical": node_categorical,
        "edge_numeric": edge_numeric,
        "edge_categorical": edge_categorical,
    }


def ordered(attrs: list[str], preferred: tuple[str, ...] = ()) -> list[str]:
    """Rimette in testa gli attributi 'preferiti' (se presenti), il resto in
    ordine alfabetico dopo. Con i nomi di colonna di un progetto specifico
    come preferred, riproduce l'ordine/i default di sempre quando quelle
    colonne esistono, e degrada senza rompersi quando non esistono."""
    head = [p for p in preferred if p in attrs]
    tail = sorted(a for a in attrs if a not in head)
    return head + tail
