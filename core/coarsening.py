"""
coarsening.py
Fusione di nodi (coarse-graining): accorpa i nodi in super-nodi in base a
un attributo (type, category, ...) oppure a una partizione in comunità
(dict {nodo: id_comunita} prodotta da metrics.detect_communities).

Il grafo risultante ha un nodo per ogni gruppo; il peso di un edge tra
due gruppi è la somma dei pesi degli edge originali che li collegano
(oppure il conteggio, a scelta).
"""

from __future__ import annotations

from collections import defaultdict

import networkx as nx


def _group_key(G: nx.Graph, node, by: str | list[str], partition: dict | None) -> str:
    """by: un nome di attributo, 'community', o una lista di questi (chiave
    composita: es. ['bipartite','category'] tiene distinti 'ente|Cultura' e
    'progetto|Cultura' invece di fonderli su un solo attributo 'category')."""
    keys = by if isinstance(by, (list, tuple)) else [by]
    parts = []
    for b in keys:
        if b == "community":
            if partition is None:
                raise ValueError("Serve 'partition' quando by include 'community'.")
            parts.append(f"Comunita_{partition[node]}")
        else:
            value = G.nodes[node].get(b)
            parts.append(str(value) if value is not None else "N/D")
    return " | ".join(parts)


def coarse_grain(
    G: nx.Graph,
    by: str | list[str] = "community",
    partition: dict | None = None,
    weight_mode: str = "sum",
    inherit_attrs: bool = True,
) -> nx.Graph:
    """
    by: 'community' (richiede partition), un nome di attributo nodo (es.
        'type', 'category'), oppure una LISTA di questi per una chiave di
        gruppo composita (es. ['bipartite','category']: raggruppa per
        categoria mantenendo distinti i due lati di un bipartito).
    weight_mode: 'sum' (somma dei pesi originali) o 'count' (numero di edge originali).
    inherit_attrs: il super-nodo eredita gli attributi originali dei membri
        (type, category, ambito, anni, ...): valori diversi uniti in una
        stringa separata da ', ' (regola di dedup.merge_attr_dicts), così
        l'export Excel della rete delle comunità mantiene le colonne
        originali. Le label dei membri finiscono in 'membri_labels'.
    """
    from .dedup import merge_attr_dicts  # import locale per evitare cicli

    C = nx.Graph()
    group_sizes = defaultdict(int)
    group_members = defaultdict(list)

    for n in G.nodes():
        g = _group_key(G, n, by, partition)
        group_sizes[g] += 1
        group_members[g].append(n)

    for g, size in group_sizes.items():
        attrs = {}
        if inherit_attrs:
            attrs = merge_attr_dicts([G.nodes[m] for m in group_members[g]],
                                      skip_prefixes=("viz_",), skip_keys=("label",))
            labels = []
            for m in group_members[g]:
                lab = str(G.nodes[m].get("label", m))
                if lab not in labels:
                    labels.append(lab)
            attrs["membri_labels"] = ", ".join(labels)
        attrs["label"] = g  # la label del super-nodo resta il nome del gruppo
        C.add_node(g, n_membri=size, membri=group_members[g], **attrs)

    for u, v, attrs in G.edges(data=True):
        gu = _group_key(G, u, by, partition)
        gv = _group_key(G, v, by, partition)
        if gu == gv:
            continue  # edge interno al gruppo: non compare nella rete "a grana grossa"
        w = attrs.get("weight", 1) if weight_mode == "sum" else 1
        if C.has_edge(gu, gv):
            C[gu][gv]["weight"] += w
            C[gu][gv]["n_edge_originali"] += 1
        else:
            C.add_edge(gu, gv, weight=w, n_edge_originali=1)

    return C


def internal_density_per_group(G: nx.Graph, by: str = "community",
                                partition: dict | None = None) -> dict:
    """Densità interna (edge/nodi) di ciascun gruppo, utile per capire quali
    comunità/categorie sono più coese internamente prima/dopo il coarse-graining."""
    from .metrics import density_links_over_nodes

    groups = defaultdict(list)
    for n in G.nodes():
        g = _group_key(G, n, by, partition)
        groups[g].append(n)

    result = {}
    for g, members in groups.items():
        sub = G.subgraph(members)
        result[g] = density_links_over_nodes(sub)
    return result
