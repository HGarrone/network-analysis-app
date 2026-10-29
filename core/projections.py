"""
projections.py
Proiezione della rete bipartita Ente<->Progetto sui due sotto-insiemi
(Ente-Ente, Progetto-Progetto), pesata per numero di legami condivisi
e/o per la somma/media dei pesi originali.

`project_by_year` calcola la proiezione separatamente per ogni anno
(snapshot o cumulativo), partendo dal grafo bipartito che porta l'anno
sugli edge — le proiezioni infatti non hanno un anno univoco per edge
e non possono essere divise a posteriori (vedi README, note metodologiche).
"""

from __future__ import annotations

import networkx as nx
from networkx.algorithms import bipartite


def _nodes_by_side(G: nx.Graph, side: str) -> list:
    return [n for n, d in G.nodes(data=True) if d.get("bipartite") == side]


def project(
    G: nx.Graph,
    on: str = "ente",
    weight_mode: str = "count",
    node_filter: dict | None = None,
) -> nx.Graph:
    """
    Proietta il grafo bipartito sul lato richiesto ('ente' o 'progetto').
    weight_mode:
      - 'count'          -> peso = numero di progetti/enti condivisi
      - 'sum_weight'      -> peso = somma dei pesi originali degli edge condivisi
      - 'jaccard'         -> peso = indice di Jaccard tra i vicinati (normalizza per dimensione)
    node_filter (opzionale): criteri stile filters.py sul lato proiettato,
    es. {"type": "Fondazione"} -> proiezione Fondazione-Fondazione via
    progetti condivisi (la "rete delle fondazioni" del brief). Diverso dal
    filtrare DOPO la proiezione completa: due fondazioni restano collegate
    dal progetto condiviso anche se al progetto partecipano altri enti,
    ma gli edge fondazione-nonfondazione non entrano mai nella rete.
    """
    from . import filters  # import locale per evitare cicli

    other = "progetto" if on == "ente" else "ente"
    nodes = _nodes_by_side(G, on)
    if node_filter:
        nodes = [n for n in nodes if filters.match_criteria(G.nodes[n], node_filter)]
    other_nodes = _nodes_by_side(G, other)
    if not nodes or not other_nodes:
        raise ValueError(f"Nessun nodo trovato per bipartite='{on}' o '{other}'"
                         + (f" con filtro {node_filter}." if node_filter else "."))

    if weight_mode == "count":
        P = bipartite.weighted_projected_graph(G, nodes)
    elif weight_mode == "jaccard":
        P = bipartite.overlap_weighted_projected_graph(G, nodes)
    elif weight_mode == "sum_weight":
        node_set = set(nodes)
        P = nx.Graph()
        P.add_nodes_from((n, G.nodes[n]) for n in nodes)
        for o in other_nodes:
            neighbors = [n for n in G.neighbors(o) if n in node_set]
            for i in range(len(neighbors)):
                for j in range(i + 1, len(neighbors)):
                    u, v = neighbors[i], neighbors[j]
                    w = G[u][o].get("weight", 1) + G[v][o].get("weight", 1)
                    if P.has_edge(u, v):
                        P[u][v]["weight"] += w
                        P[u][v]["shared"] += 1
                    else:
                        P.add_edge(u, v, weight=w, shared=1)
    else:
        raise ValueError(f"weight_mode non riconosciuto: {weight_mode}")

    # le funzioni bipartite di networkx includono anche i "secondi vicini"
    # fuori dal sottoinsieme richiesto: con un filtro attivo, restringiamo
    # la proiezione ai soli nodi filtrati
    if node_filter:
        P = P.subgraph(nodes).copy()

    # riporta attributi originali sui nodi (persi da alcune funzioni bipartite)
    for n in P.nodes():
        P.nodes[n].update(G.nodes[n])
    return P


def project_by_year(G: nx.Graph, on: str = "ente", weight_mode: str = "count",
                     mode: str = "snapshot", year_attr: str = "anno",
                     node_filter: dict | None = None) -> dict:
    """
    Proiezione calcolata separatamente per ogni anno: divide prima il grafo
    bipartito per anno (temporal.split_by_year, mode='snapshot' o
    'cumulative'), poi proietta ciascun sottografo annuale sul lato richiesto.
    Ritorna {anno: grafo_proiettato}. Gli anni senza nodi su entrambi i lati
    vengono saltati.
    """
    from . import temporal  # import locale per evitare cicli

    graphs_by_year = temporal.split_by_year(G, mode=mode, year_attr=year_attr)
    result = {}
    for y, g in graphs_by_year.items():
        try:
            result[y] = project(g, on=on, weight_mode=weight_mode, node_filter=node_filter)
        except ValueError:
            continue  # anno senza nodi di uno dei due lati (o nessun nodo nel filtro)
    return result
