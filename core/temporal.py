"""
temporal.py
Divisione della rete negli anni (o in un qualunque timestamp presente sugli
edge) e calcolo delle metriche nel tempo, in due modalità:

- 'snapshot'  : un grafo per ciascun anno, contenente solo gli edge di
                quell'anno (immagine "a quel momento").
- 'cumulative': un grafo per ciascun anno, contenente tutti gli edge fino
                a quell'anno incluso (rete che cresce nel tempo).

Entrambe le modalità sono utili e rispondono a domande diverse: lo snapshot
mostra l'attività del singolo anno, il cumulativo mostra la crescita/persistenza
delle relazioni.
"""

from __future__ import annotations

import networkx as nx


def get_edge_years(G: nx.Graph, year_attr: str = "anno") -> list[int]:
    # G.edges(data=True) itera correttamente sia su Graph che su MultiGraph
    # (senza bisogno di keys=True), a differenza di G.edges[e] con e a 2 elementi.
    years = {data.get(year_attr) for _, _, data in G.edges(data=True)}
    years.discard(None)
    return sorted(years)


def split_by_year(G: nx.Graph, mode: str = "snapshot", year_attr: str = "anno") -> dict:
    """
    mode: 'snapshot' o 'cumulative'.
    Ritorna {anno: sottografo}.
    I nodi isolati (senza edge in quell'anno/fino a quell'anno) vengono rimossi
    dal sottografo, per non falsare densità/degree con nodi "vuoti".
    """
    years = get_edge_years(G, year_attr)
    all_edges = list(G.edges(data=True))
    result = {}
    for y in years:
        if mode == "snapshot":
            edges = [(u, v, d) for u, v, d in all_edges if d.get(year_attr) == y]
        elif mode == "cumulative":
            edges = [(u, v, d) for u, v, d in all_edges if d.get(year_attr) is not None
                     and d.get(year_attr) <= y]
        else:
            raise ValueError("mode deve essere 'snapshot' o 'cumulative'.")

        H = nx.Graph()
        H.add_nodes_from(G.nodes(data=True))  # mantiene attributi nodo
        for u, v, d in edges:
            H.add_edge(u, v, **d)
        H.remove_nodes_from(list(nx.isolates(H)))
        result[y] = H
    return result


def metrics_over_time(G: nx.Graph, mode: str = "snapshot", year_attr: str = "anno",
                       entropy_attribute: str = "category",
                       community_method: str = "louvain") -> dict:
    """Applica metrics.full_metrics_report a ogni anno; utile per grafici di trend."""
    from .metrics import full_metrics_report  # import locale per evitare cicli

    graphs_by_year = split_by_year(G, mode=mode, year_attr=year_attr)
    return {
        y: full_metrics_report(g, entropy_attribute=entropy_attribute,
                                community_method=community_method)
        for y, g in graphs_by_year.items()
    }


def trend_table(metrics_by_year: dict, metric_path: list[str]) -> dict:
    """
    Estrae una serie temporale semplice da metrics_over_time, navigando il
    dict annidato. Es: trend_table(m, ['densita', 'densita_links_su_nodi'])
    -> {2022: 3.1, 2023: 3.4, ...}
    """
    out = {}
    for year, report in metrics_by_year.items():
        val = report
        for key in metric_path:
            val = val[key]
        out[year] = val
    return out
