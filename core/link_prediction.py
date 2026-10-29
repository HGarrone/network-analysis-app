"""
link_prediction.py
Previsione dei legami mancanti/futuri con i metodi classici di similarità
strutturale (networkx), più la validazione con hold-out temporale che il
dataset permette (train sugli anni passati, test sull'anno successivo).

Uso tipico: suggerire potenziali collaborazioni tra enti. NOTA: i metodi
di similarità presuppongono un grafo UNIPARTITO (es. la proiezione
Ente-Ente): sul bipartito due nodi dello stesso lato non sono mai adiacenti
e i punteggi degradano — usare le proiezioni.

Funzioni:
- `predict_links(G, method, top_k)` — coppie non collegate più promettenti.
- `temporal_holdout(G_bipartite, test_year, on, method, top_k)` — valuta il
  metodo: allena sulla rete cumulativa fino all'anno precedente, verifica
  quali nuovi legami dell'anno di test erano stati previsti (precision@k).
Espandibile: aggiungere un metodo = una entry in METHODS.
"""

from __future__ import annotations

import networkx as nx


def _common_neighbors(G, pairs):
    for u, v in pairs:
        yield u, v, len(list(nx.common_neighbors(G, u, v)))


def _preferential_attachment(G, pairs):
    return nx.preferential_attachment(G, pairs)


# nome -> funzione(G, ebunch) -> iteratore (u, v, score)
METHODS = {
    "common_neighbors": _common_neighbors,
    "jaccard": nx.jaccard_coefficient,
    "adamic_adar": nx.adamic_adar_index,
    "resource_allocation": nx.resource_allocation_index,
    "preferential_attachment": _preferential_attachment,
}


def candidate_pairs(G: nx.Graph, max_distance: int = 2) -> list[tuple]:
    """
    Coppie non collegate candidate: di default solo nodi a distanza 2
    (con almeno un vicino in comune) — è dove i metodi di similarità sono
    informativi, ed evita l'esplosione O(n²) delle coppie qualsiasi.
    max_distance=None per tutte le non-adiacenze.
    """
    if max_distance is None:
        return list(nx.non_edges(G))
    pairs = set()
    for n in G.nodes():
        for nb in G.neighbors(n):
            for nb2 in G.neighbors(nb):
                if nb2 != n and not G.has_edge(n, nb2):
                    pairs.add((n, nb2) if str(n) <= str(nb2) else (nb2, n))
    return sorted(pairs)


def predict_links(G: nx.Graph, method: str = "adamic_adar", top_k: int = 20,
                   pairs: list | None = None) -> list[dict]:
    """
    Le top_k coppie non collegate con punteggio più alto secondo il metodo.
    Ritorna righe {u, v, label_u, label_v, score} ordinate per score
    decrescente (pronte per un DataFrame).
    """
    if method not in METHODS:
        raise ValueError(f"Metodo '{method}' non riconosciuto. Disponibili: {list(METHODS)}")
    if isinstance(G, nx.MultiGraph):
        raise ValueError("Serve un grafo semplice: componi il multiplex con 'Unisci tutto'.")
    pairs = pairs if pairs is not None else candidate_pairs(G)
    if not pairs:
        return []
    scored = METHODS[method](G, pairs)
    top = sorted(scored, key=lambda t: t[2], reverse=True)[:top_k]
    return [{"u": u, "v": v,
              "label_u": G.nodes[u].get("label", u),
              "label_v": G.nodes[v].get("label", v),
              "score": round(float(s), 4)}
             for u, v, s in top if s > 0]


def temporal_holdout(G_bipartite: nx.Graph, test_year, on: str = "ente",
                      weight_mode: str = "count", method: str = "adamic_adar",
                      top_k: int = 20) -> dict:
    """
    Valutazione con hold-out temporale:
    - TRAIN: proiezione della rete cumulativa fino all'anno PRIMA di test_year
    - TEST:  i legami della proiezione cumulativa fino a test_year che non
             esistevano nel train (solo tra nodi già presenti nel train:
             i nodi nuovi non sono prevedibili da un metodo strutturale)
    Ritorna {previsioni, nuovi_legami_osservati, precision_at_k, hits, n_test}.
    """
    from . import temporal, projections  # import locale per evitare cicli

    graphs = temporal.split_by_year(G_bipartite, mode="cumulative")
    years = sorted(graphs)
    if test_year not in years:
        raise ValueError(f"Anno {test_year} non presente. Disponibili: {years}")
    prev_years = [y for y in years if y < test_year]
    if not prev_years:
        raise ValueError(f"Nessun anno precedente a {test_year} su cui allenare.")

    train = projections.project(graphs[prev_years[-1]], on=on, weight_mode=weight_mode)
    test = projections.project(graphs[test_year], on=on, weight_mode=weight_mode)

    def key(u, v):
        return (u, v) if str(u) <= str(v) else (v, u)

    train_edges = {key(u, v) for u, v in train.edges()}
    test_new = {key(u, v) for u, v in test.edges()
                if key(u, v) not in train_edges and u in train and v in train}

    preds = predict_links(train, method=method, top_k=top_k)
    hits = [r for r in preds if key(r["u"], r["v"]) in test_new]
    return {
        "anno_test": test_year,
        "anni_train": prev_years,
        "previsioni": preds,
        "n_nuovi_legami_osservati": len(test_new),
        "hits": hits,
        "n_hits": len(hits),
        "precision_at_k": round(len(hits) / len(preds), 3) if preds else 0.0,
    }
