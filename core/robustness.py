"""
robustness.py
Analisi di robustezza/dipendenza della rete (dimensione "Health" del
framework SNA, brief §1.2): quanto la rete dipende da singoli nodi e come
si frammenta se i nodi più centrali escono.

Due strumenti complementari:
- `key_node_dependency(G)` — per ciascuno dei nodi più centrali, cosa
  succede rimuovendo SOLO quel nodo (componenti, dimensione della componente
  maggiore, edge persi). Risponde a "quanto siamo dipendenti dal partner X?".
- `attack_simulation(G)` — rimozione progressiva dei nodi più centrali
  (o casuali, come baseline) e traiettoria della frammentazione. Il
  confronto attacco-mirato vs casuale è la misura classica di ridondanza:
  una rete sana degrada in modo simile nei due casi, una rete dipendente
  da pochi hub collassa subito sotto attacco mirato.

Come per data_table.remove_nodes, il grafo di partenza non viene mai toccato.
"""

from __future__ import annotations

import random

import networkx as nx

from . import metrics as metrics_mod


def _largest_component_size(G: nx.Graph) -> int:
    if G.number_of_nodes() == 0:
        return 0
    return max(len(c) for c in nx.connected_components(G))


def _ranked_nodes(G: nx.Graph, strategy: str, seed: int = 42) -> list:
    """Nodi ordinati dal più 'importante' secondo la strategia scelta."""
    if strategy == "degree":
        return sorted(G.nodes(), key=lambda n: G.degree(n), reverse=True)
    if strategy == "degree_pesato":
        return sorted(G.nodes(), key=lambda n: G.degree(n, weight="weight"), reverse=True)
    if strategy == "betweenness":
        bc = metrics_mod.betweenness_centrality(G)
        return sorted(G.nodes(), key=lambda n: bc[n], reverse=True)
    if strategy == "random":
        nodes = list(G.nodes())
        random.Random(seed).shuffle(nodes)
        return nodes
    raise ValueError(f"Strategia non riconosciuta: {strategy}. "
                     "Disponibili: degree, degree_pesato, betweenness, random.")


def key_node_dependency(G: nx.Graph, top_n: int = 10, strategy: str = "degree") -> list[dict]:
    """
    Per ciascuno dei top_n nodi più centrali: effetto della rimozione del
    SOLO quel nodo. Ritorna una lista di righe (una per nodo) con label,
    centralità, edge persi, numero di componenti e dimensione della
    componente maggiore dopo la rimozione — pronta per un DataFrame.
    """
    base_components = nx.number_connected_components(G)
    base_largest = _largest_component_size(G)
    rows = []
    for n in _ranked_nodes(G, strategy)[:top_n]:
        H = G.copy()
        H.remove_node(n)
        rows.append({
            "node_id": n,
            "label": G.nodes[n].get("label", n),
            "degree": G.degree(n),
            "edge_persi": G.degree(n),
            "n_componenti_dopo": nx.number_connected_components(H),
            "delta_componenti": nx.number_connected_components(H) - base_components,
            "dim_componente_maggiore_dopo": _largest_component_size(H),
            "delta_componente_maggiore": _largest_component_size(H) - base_largest,
        })
    return rows


def attack_simulation(G: nx.Graph, strategy: str = "degree", steps: int = 10,
                       max_fraction: float = 0.5, recompute: bool = True,
                       seed: int = 42) -> list[dict]:
    """
    Rimozione progressiva dei nodi (fino a max_fraction del totale, in
    `steps` passi) secondo la strategia scelta; a ogni passo registra
    frammentazione e densità. Con recompute=True la classifica dei nodi
    viene ricalcolata dopo ogni passo (attacco adattivo, più realistico);
    con False si usa la classifica iniziale (più veloce).
    Ritorna una lista di righe {frazione_rimossa, n_nodi, n_edge,
    n_componenti, dim_componente_maggiore, densita_links_su_nodi}.
    """
    H = G.copy()
    n_total = G.number_of_nodes()
    if n_total == 0:
        return []
    per_step = max(1, round(n_total * max_fraction / steps))
    ranking = [] if recompute else _ranked_nodes(H, strategy, seed)

    def _row(removed):
        return {
            "nodi_rimossi": removed,
            "frazione_rimossa": removed / n_total,
            "n_nodi": H.number_of_nodes(),
            "n_edge": H.number_of_edges(),
            "n_componenti": nx.number_connected_components(H) if H.number_of_nodes() else 0,
            "dim_componente_maggiore": _largest_component_size(H),
            "densita_links_su_nodi": metrics_mod.density_links_over_nodes(H),
        }

    rows = [_row(0)]
    removed = 0
    while removed < n_total * max_fraction and H.number_of_nodes() > 0:
        batch = (_ranked_nodes(H, strategy, seed)[:per_step] if recompute
                 else ranking[removed:removed + per_step])
        batch = [n for n in batch if n in H]
        if not batch:
            break
        H.remove_nodes_from(batch)
        removed += len(batch)
        rows.append(_row(removed))
    return rows
