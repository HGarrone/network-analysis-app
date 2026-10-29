"""
comparison.py
Confronto tra due reti/snapshot (es. due anni della rete bipartita, o la
stessa proiezione prima/dopo una pulizia): nodi entrati/usciti, edge
entrati/usciti, differenza di degree per i nodi comuni, delta delle metriche
di sintesi. Utile per leggere l'evoluzione della rete secondo il ciclo di
vita del network (Inception -> Growth -> Maturity, vedi brief teorico §1.6).

Due livelli d'uso:
- `compare_graphs(G1, G2)` — confronto generico tra due grafi qualsiasi,
  ritorna un dict con insiemi e delta.
- `compare_years(G, y1, y2, mode)` — scorciatoia: divide il grafo bipartito
  per anno (temporal.split_by_year) e confronta i due anni scelti.
- `delta_table(result, G1, G2)` — la parte per-nodo del confronto come
  DataFrame pandas ordinabile (stile data_table.py), con label leggibili.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd

from . import metrics as metrics_mod
from . import temporal


def _edge_key(u, v) -> tuple:
    """Chiave non orientata dell'edge (per confronto tra grafi)."""
    return (u, v) if str(u) <= str(v) else (v, u)


def compare_graphs(G1: nx.Graph, G2: nx.Graph, labels: tuple[str, str] = ("prima", "dopo")) -> dict:
    """
    Confronta due grafi (G1 = 'prima', G2 = 'dopo'). Ritorna:
      - nodi: entrati (solo in G2), usciti (solo in G1), comuni
      - edge: entrati, usciti (per chiave non orientata)
      - degree_delta: per ogni nodo comune {prima, dopo, delta},
        sia per il degree semplice sia per quello pesato
      - sintesi: (valore_G1, valore_G2, delta) per nodi, edge e densità
    """
    n1, n2 = set(G1.nodes()), set(G2.nodes())
    e1 = {_edge_key(u, v) for u, v in G1.edges()}
    e2 = {_edge_key(u, v) for u, v in G2.edges()}

    common = n1 & n2
    deg1, deg2 = dict(G1.degree()), dict(G2.degree())
    wdeg1, wdeg2 = dict(G1.degree(weight="weight")), dict(G2.degree(weight="weight"))
    degree_delta = {
        n: {
            "degree_prima": deg1[n], "degree_dopo": deg2[n],
            "degree_delta": deg2[n] - deg1[n],
            "degree_pesato_prima": wdeg1[n], "degree_pesato_dopo": wdeg2[n],
            "degree_pesato_delta": wdeg2[n] - wdeg1[n],
        }
        for n in common
    }

    def _sintesi(val1, val2):
        return {labels[0]: val1, labels[1]: val2, "delta": val2 - val1}

    return {
        "labels": labels,
        "nodi": {
            "entrati": sorted(n2 - n1, key=str),
            "usciti": sorted(n1 - n2, key=str),
            "comuni": sorted(common, key=str),
        },
        "edge": {
            "entrati": sorted(e2 - e1),
            "usciti": sorted(e1 - e2),
            "comuni": sorted(e1 & e2),
        },
        "degree_delta": degree_delta,
        "sintesi": {
            "n_nodi": _sintesi(G1.number_of_nodes(), G2.number_of_nodes()),
            "n_edge": _sintesi(G1.number_of_edges(), G2.number_of_edges()),
            "densita_links_su_nodi": _sintesi(
                metrics_mod.density_links_over_nodes(G1),
                metrics_mod.density_links_over_nodes(G2)),
            "densita_standard_0_1": _sintesi(
                metrics_mod.density_standard(G1),
                metrics_mod.density_standard(G2)),
        },
    }


def compare_years(G: nx.Graph, year1, year2, mode: str = "snapshot",
                   year_attr: str = "anno") -> dict:
    """
    Scorciatoia: confronta due anni della rete (tipicamente il bipartito,
    che porta l'anno sugli edge). mode='snapshot' o 'cumulative'.
    """
    graphs_by_year = temporal.split_by_year(G, mode=mode, year_attr=year_attr)
    for y in (year1, year2):
        if y not in graphs_by_year:
            raise ValueError(f"Anno {y} non presente nella rete. "
                             f"Anni disponibili: {sorted(graphs_by_year)}")
    return compare_graphs(graphs_by_year[year1], graphs_by_year[year2],
                           labels=(str(year1), str(year2)))


def delta_table(result: dict, G1: nx.Graph, G2: nx.Graph) -> pd.DataFrame:
    """
    La parte per-nodo del confronto come DataFrame (una riga per nodo comune,
    più i nodi entrati/usciti con stato dedicato), ordinabile in stile
    data_table.py. Colonne: node_id, label, stato, degree prima/dopo/delta.
    """
    rows = []
    for n in result["nodi"]["comuni"]:
        row = {"node_id": n,
               "label": G2.nodes[n].get("label", G1.nodes[n].get("label", n)),
               "stato": "comune"}
        row.update(result["degree_delta"][n])
        rows.append(row)
    for n in result["nodi"]["entrati"]:
        rows.append({"node_id": n, "label": G2.nodes[n].get("label", n),
                      "stato": "entrato", "degree_dopo": G2.degree(n)})
    for n in result["nodi"]["usciti"]:
        rows.append({"node_id": n, "label": G1.nodes[n].get("label", n),
                      "stato": "uscito", "degree_prima": G1.degree(n)})
    if not rows:
        return pd.DataFrame(columns=["node_id", "label", "stato"])
    return pd.DataFrame(rows).sort_values(
        by="degree_delta", ascending=False, na_position="last").reset_index(drop=True)
