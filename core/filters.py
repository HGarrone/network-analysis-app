"""
filters.py
Due tipi di filtro, entrambi espressi come criteri su attributi dei nodi
(o degli edge):

1. Filtro di SELEZIONE: costruisce una sotto-rete vera e propria a partire
   da un criterio (es. Type == 'Fondazione'). Il risultato è un nuovo grafo
   utilizzabile per qualunque analisi (densità, entropia, comunità, ...) o
   come "seme" per un'ego-network (vedi ego.py).

2. Filtro di VISUALIZZAZIONE: non altera il grafo per il calcolo, ma
   restituisce l'insieme di nodi/edge da mostrare/nascondere quando si
   disegna la rete (utile nella GUI, dove si vuole esplorare senza
   ricalcolare le metriche ogni volta).

I criteri sono espressi come dict: {attributo: valore | lista di valori}.
Esempio: {"type": "Fondazione"} oppure {"category": ["Cultura", "Sociale"]}
"""

from __future__ import annotations

import networkx as nx


def _match(value, criterion) -> bool:
    if isinstance(criterion, (list, tuple, set)):
        return value in criterion
    return value == criterion


def match_criteria(attrs: dict, criteria: dict) -> bool:
    """True se il dizionario di attributi soddisfa TUTTI i criteri (AND logico)."""
    for key, criterion in criteria.items():
        if key not in attrs:
            return False
        if not _match(attrs[key], criterion):
            return False
    return True


def select_nodes(G: nx.Graph, criteria: dict) -> list:
    """Restituisce la lista di nodi che soddisfano i criteri (filtro di selezione)."""
    return [n for n, attrs in G.nodes(data=True) if match_criteria(attrs, criteria)]


def build_subgraph(G: nx.Graph, criteria: dict, keep_neighbors: bool = False) -> nx.Graph:
    """
    Filtro di SELEZIONE: costruisce una sotto-rete indotta dai nodi che
    soddisfano i criteri.
    - keep_neighbors=False -> sotto-rete indotta solo sui nodi selezionati
      (edge solo tra nodi che soddisfano entrambi il criterio).
    - keep_neighbors=True  -> include anche i vicini diretti dei nodi
      selezionati (utile per non isolare troppo la sotto-rete).
    """
    selected = select_nodes(G, criteria)
    if keep_neighbors:
        expanded = set(selected)
        for n in selected:
            expanded.update(G.neighbors(n))
        selected = list(expanded)
    return G.subgraph(selected).copy()


def build_edge_subgraph(G: nx.Graph, edge_criteria: dict) -> nx.Graph:
    """Filtro di selezione sugli EDGE (es. {'interaction_type': 'Partner'})."""
    H = nx.Graph()
    H.add_nodes_from(G.nodes(data=True))
    for u, v, attrs in G.edges(data=True):
        if match_criteria(attrs, edge_criteria):
            H.add_edge(u, v, **attrs)
    # rimuove i nodi rimasti isolati dal filtro sugli edge
    isolated = list(nx.isolates(H))
    H.remove_nodes_from(isolated)
    return H


def visualization_mask(G: nx.Graph, criteria: dict | None = None,
                        edge_criteria: dict | None = None) -> tuple[set, set]:
    """
    Filtro di VISUALIZZAZIONE: non modifica il grafo, restituisce solo
    (nodi_da_mostrare, edge_da_mostrare) da usare nel layer grafico.
    Utile nella GUI per un filtro rapido senza ricalcolare le metriche.
    """
    nodes_to_show = set(select_nodes(G, criteria)) if criteria else set(G.nodes())
    edges_to_show = set()
    for u, v, attrs in G.edges(data=True):
        node_ok = (u in nodes_to_show and v in nodes_to_show)
        edge_ok = match_criteria(attrs, edge_criteria) if edge_criteria else True
        if node_ok and edge_ok:
            edges_to_show.add((u, v))
    return nodes_to_show, edges_to_show
