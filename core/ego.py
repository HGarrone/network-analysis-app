"""
ego.py
Ego-network generalizzata: il "seme" (ego) può essere un singolo nodo oppure
un insieme di nodi definito da un filtro (vedi filters.py), es. tutti i nodi
con Type == 'Fondazione'.

Restituisce, per ogni raggio r=1,2,...,max_hops:
- la sotto-rete "interna" (seme + vicini entro r passi)
- l'insieme dei nodi "esterni" (tutto il resto del grafo)
"""

from __future__ import annotations

import networkx as nx

from .filters import select_nodes


def resolve_seed(G: nx.Graph, seed=None, seed_filter: dict | None = None) -> set:
    """
    Risolve il seme dell'ego-network:
    - seed: un nodo o una lista di nodi
    - seed_filter: criteri (vedi filters.py) per selezionare il seme per attributo
    Uno dei due deve essere fornito.
    """
    if seed is None and seed_filter is None:
        raise ValueError("Serve un 'seed' (nodo/lista) oppure un 'seed_filter' (criteri).")
    nodes = set()
    if seed is not None:
        nodes.update(seed if isinstance(seed, (list, tuple, set)) else [seed])
    if seed_filter is not None:
        nodes.update(select_nodes(G, seed_filter))
    missing = [n for n in nodes if n not in G]
    if missing:
        raise ValueError(f"Nodi seme non presenti nel grafo: {missing}")
    return nodes


def ego_network_by_degree(
    G: nx.Graph,
    seed=None,
    seed_filter: dict | None = None,
    max_hops: int = 2,
) -> dict:
    """
    Calcola l'ego-network a più gradi di distanza dal seme.
    Ritorna un dict:
      {
        1: {"subgraph": G1, "internal_nodes": {...}, "external_nodes": {...}},
        2: {"subgraph": G2, ...},
        ...
      }
    dove G_r è indotto sui nodi a distanza <= r dal seme.
    """
    seed_nodes = resolve_seed(G, seed, seed_filter)
    results = {}
    for r in range(1, max_hops + 1):
        internal = set(seed_nodes)
        for s in seed_nodes:
            # nx.single_source_shortest_path_length gestisce grafi pesati o meno
            # allo stesso modo per il numero di hop (non usa i pesi)
            lengths = nx.single_source_shortest_path_length(G, s, cutoff=r)
            internal.update(lengths.keys())
        external = set(G.nodes()) - internal
        results[r] = dict(
            subgraph=G.subgraph(internal).copy(),
            internal_nodes=internal,
            external_nodes=external,
        )
    return results


def neighbors_shell(G: nx.Graph, seed=None, seed_filter: dict | None = None, hop: int = 1) -> set:
    """Restituisce solo i nodi ESATTAMENTE a distanza `hop` dal seme (shell, non palla piena)."""
    seed_nodes = resolve_seed(G, seed, seed_filter)
    shell = set()
    for s in seed_nodes:
        lengths = nx.single_source_shortest_path_length(G, s, cutoff=hop)
        shell.update(n for n, d in lengths.items() if d == hop)
    return shell - seed_nodes
