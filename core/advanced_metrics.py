"""
advanced_metrics.py
Metriche di network science aggiuntive rispetto a metrics.py/granular.py,
sullo stesso principio del resto della pipeline: funzioni pure, nessun
side-effect, pensate per essere richiamate MANUALMENTE da bottoni nella
GUI (non una pipeline automatica). Riferimento concettuale:
analisi_rete_generale_v78.R (centralità aggiuntive, k-core, misure di
Burt, chiusura triadica, omofilia vs modello nullo, specializzazione HHI,
concentrazione di Lorenz, distribuzione dei gradi, confronto tra
centralità) — qui riproposte come analisi puntuali che l'utente sceglie di
lanciare, non un report automatico.
"""

from __future__ import annotations

import math
import random
from collections import Counter

import networkx as nx
import pandas as pd

from . import metrics as metrics_mod


def _clean_num(x):
    """None/NaN -> None (nx.effective_size/constraint restituiscono NaN
    per i nodi senza vicini o con un solo vicino)."""
    if x is None:
        return None
    try:
        if math.isnan(x):
            return None
    except TypeError:
        pass
    return x


# ---------------------------------------------------------------------------
# Centralità aggiuntive (oltre a degree/betweenness già in metrics.py)
# ---------------------------------------------------------------------------

def eigenvector_centrality(G: nx.Graph, weight: str | None = None) -> dict:
    """Variante numpy: robusta anche su grafi disconnessi o con problemi di
    convergenza del metodo iterativo classico."""
    if G.number_of_nodes() == 0:
        return {}
    try:
        return nx.eigenvector_centrality_numpy(G, weight=weight)
    except Exception:
        return {n: 0.0 for n in G.nodes()}


def pagerank_centrality(G: nx.Graph, weight: str | None = "weight") -> dict:
    if G.number_of_nodes() == 0:
        return {}
    return nx.pagerank(G, weight=weight)


def closeness_centrality(G: nx.Graph) -> dict:
    if G.number_of_nodes() == 0:
        return {}
    return nx.closeness_centrality(G)


def centrality_correlation(G: nx.Graph, weight: str | None = "weight") -> pd.DataFrame:
    """Matrice di correlazione (Pearson) tra le misure di centralità
    disponibili: valori vicini a 1 indicano misure ridondanti (una delle
    due basta), valori bassi indicano che catturano aspetti diversi."""
    measures = {
        "degree": dict(G.degree()),
        "betweenness": metrics_mod.betweenness_centrality(G),
        "eigenvector": eigenvector_centrality(G, weight=weight),
        "pagerank": pagerank_centrality(G, weight=weight),
        "closeness": closeness_centrality(G),
    }
    return pd.DataFrame(measures).corr()


# ---------------------------------------------------------------------------
# k-core
# ---------------------------------------------------------------------------

def core_numbers(G: nx.Graph) -> dict:
    """Core number di ogni nodo (richiede un grafo semplice senza self-loop)."""
    H = nx.Graph(G)
    H.remove_edges_from(nx.selfloop_edges(H))
    return nx.core_number(H)


def k_core_subgraph(G: nx.Graph, k: int) -> nx.Graph:
    H = nx.Graph(G)
    H.remove_edges_from(nx.selfloop_edges(H))
    return nx.k_core(H, k=k)


def k_core_plateau(G: nx.Graph) -> pd.DataFrame:
    """Dimensione (nodi/edge) del k-core al variare di k: dove smette di
    ridursi bruscamente ('plateau') indica il nucleo strutturale della rete."""
    cn = core_numbers(G)
    if not cn:
        return pd.DataFrame(columns=["k", "n_nodi", "n_edge"])
    kmax = max(cn.values())
    rows = [{"k": k, "n_nodi": (sub := k_core_subgraph(G, k)).number_of_nodes(),
             "n_edge": sub.number_of_edges()} for k in range(0, kmax + 1)]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Misure di Burt (ridondanza dei legami / potenziale di brokeraggio)
# ---------------------------------------------------------------------------

def burt_measures(G: nx.Graph, weight: str | None = None) -> pd.DataFrame:
    """Effective size, efficiency (= effective_size / degree) e constraint
    per nodo. Effective size alto + constraint basso = il nodo collega
    gruppi altrimenti non ridondanti tra loro (buon broker)."""
    eff_size = nx.effective_size(G, weight=weight)
    constraint = nx.constraint(G, weight=weight)
    degree = dict(G.degree())
    rows = []
    for n in G.nodes():
        es = _clean_num(eff_size.get(n))
        deg = degree.get(n, 0)
        efficiency = (es / deg) if (es is not None and deg) else None
        rows.append({
            "node_id": n, "label": G.nodes[n].get("label", n),
            "effective_size": round(es, 4) if es is not None else None,
            "efficiency": round(efficiency, 4) if efficiency is not None else None,
            "constraint": round(c, 4) if (c := _clean_num(constraint.get(n))) is not None else None,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Triadi aperte / chiusura triadica (globale e per gruppo)
# ---------------------------------------------------------------------------

def triad_closure(G: nx.Graph) -> dict:
    """Triple connesse (wedge) totali, quante sono chiuse in un triangolo,
    quante restano aperte, e il tasso di chiusura (= transitivity globale)."""
    triangles = sum(nx.triangles(G).values()) // 3
    wedges = sum(d * (d - 1) // 2 for _, d in G.degree())
    rate = (3 * triangles / wedges) if wedges else None
    return {"triangoli": triangles, "triple_totali": wedges,
            "triple_aperte": wedges - 3 * triangles,
            "tasso_chiusura": round(rate, 4) if rate is not None else None}


def triad_closure_per_group(G: nx.Graph, group_attr: str | None = None,
                             partition: dict | None = None) -> pd.DataFrame:
    """Come triad_closure, calcolato sul sottografo indotto di ogni gruppo
    (per attributo nodo, o per comunità passando una partizione)."""
    groups: dict = {}
    if partition is not None:
        for n, cid in partition.items():
            groups.setdefault(f"Comunita_{cid}", []).append(n)
    elif group_attr:
        for n in G.nodes():
            groups.setdefault(str(G.nodes[n].get(group_attr)), []).append(n)
    else:
        raise ValueError("Serve group_attr o partition.")
    rows = [{"gruppo": g, "n_nodi": len(nodes), **triad_closure(G.subgraph(nodes))}
            for g, nodes in groups.items()]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Matrice di mixing + omofilia vs modello nullo
# ---------------------------------------------------------------------------

def mixing_matrix(G: nx.Graph, attribute: str) -> pd.DataFrame:
    """Quante coppie di legami cadono in ogni combinazione di valori
    dell'attributo sui due estremi (righe/colonne = valori distinti)."""
    values = sorted({str(G.nodes[n].get(attribute)) for n in G.nodes()
                      if G.nodes[n].get(attribute) is not None})
    idx = {v: i for i, v in enumerate(values)}
    mat = [[0] * len(values) for _ in values]
    for u, v in G.edges():
        a, b = G.nodes[u].get(attribute), G.nodes[v].get(attribute)
        if a is None or b is None:
            continue
        ia, ib = idx[str(a)], idx[str(b)]
        mat[ia][ib] += 1
        if ia != ib:
            mat[ib][ia] += 1
    return pd.DataFrame(mat, index=values, columns=values)


def homophily_vs_null(G: nx.Graph, attribute: str, n_reps: int = 200,
                       seed: int | None = 42) -> dict:
    """
    Test di omofilia: confronta l'indice E-I osservato (granular.ei_index:
    -1 = tutti i legami interni alla stessa categoria, +1 = tutti tra
    categorie diverse) con la distribuzione ottenuta rimescolando a caso i
    valori dell'attributo tra i nodi (modello nullo, n_reps ripetizioni).
    |z_score| > 1.96 indica un'omofilia (o eterofilia) non spiegabile dal
    caso, alla soglia usuale del 5%.
    """
    from . import granular as granular_mod

    observed = granular_mod.ei_index(G, attribute)
    if observed is None:
        return {"osservato": None, "media_nulla": None, "deviazione_standard_nulla": None,
                "z_score": None, "n_ripetizioni": 0, "interpretazione": "dati insufficienti"}

    rng = random.Random(seed)
    values = [G.nodes[n].get(attribute) for n in G.nodes()]
    nodes = list(G.nodes())
    H = G.copy()
    nulls = []
    for _ in range(n_reps):
        shuffled = values[:]
        rng.shuffle(shuffled)
        for n, v in zip(nodes, shuffled):
            H.nodes[n][attribute] = v
        e_i = granular_mod.ei_index(H, attribute)
        if e_i is not None:
            nulls.append(e_i)

    if not nulls:
        return {"osservato": round(observed, 4), "media_nulla": None,
                "deviazione_standard_nulla": None, "z_score": None,
                "n_ripetizioni": 0, "interpretazione": "modello nullo non calcolabile"}

    mean_null = sum(nulls) / len(nulls)
    std_null = math.sqrt(sum((x - mean_null) ** 2 for x in nulls) / len(nulls))
    z = (observed - mean_null) / std_null if std_null > 0 else None
    interpretazione = "non distinguibile dal caso (|z|<1.96)"
    if z is not None and abs(z) >= 1.96:
        interpretazione = "più omofilo del caso" if z < 0 else "più eterofilo del caso"
    return {"osservato": round(observed, 4), "media_nulla": round(mean_null, 4),
            "deviazione_standard_nulla": round(std_null, 4),
            "z_score": round(z, 4) if z is not None else None,
            "n_ripetizioni": len(nulls), "interpretazione": interpretazione}


# ---------------------------------------------------------------------------
# Specializzazione (indice HHI)
# ---------------------------------------------------------------------------

def hhi(values: list) -> float:
    """Indice di Herfindahl-Hirschman: sum(p_i^2) sulla distribuzione di
    `values` — 1/k (k = n. categorie) se equidistribuito, 1 se concentrato
    su un solo valore. Convenzione 0-1 (non ×10000 come nell'antitrust)."""
    counts = Counter(values)
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return sum((c / total) ** 2 for c in counts.values())


def specialization_per_node(G: nx.Graph, attribute: str) -> dict:
    """HHI della distribuzione dell'attributo TRA I VICINI di ogni nodo:
    quanto ogni nodo concentra i propri legami su poche categorie invece di
    distribuirli — la versione 'a concentrazione' (anziché a diversità)
    dell'entropia di vicinato già in metrics.neighbor_entropy."""
    result = {}
    for n in G.nodes():
        neigh_vals = [G.nodes[nb].get(attribute) for nb in G.neighbors(n)
                       if G.nodes[nb].get(attribute) is not None]
        result[n] = round(hhi(neigh_vals), 4) if neigh_vals else None
    return result


def specialization_per_group(G: nx.Graph, group_attr: str, target_attr: str) -> pd.DataFrame:
    """Per ogni gruppo (valore di group_attr), HHI della distribuzione di
    target_attr tra tutti i vicini dei membri del gruppo: quanto quel
    gruppo è 'specializzato' nel connettersi verso poche categorie
    dell'altra dimensione, invece di essere generalista."""
    groups: dict = {}
    for n in G.nodes():
        groups.setdefault(str(G.nodes[n].get(group_attr)), []).append(n)
    rows = []
    for g, gnodes in groups.items():
        neigh_vals = []
        for n in gnodes:
            neigh_vals += [G.nodes[nb].get(target_attr) for nb in G.neighbors(n)
                            if G.nodes[nb].get(target_attr) is not None]
        rows.append({"gruppo": g, "n_nodi": len(gnodes), "n_legami_osservati": len(neigh_vals),
                     "hhi": round(hhi(neigh_vals), 4) if neigh_vals else None})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Concentrazione: Gini generalizzato + curva di Lorenz
# ---------------------------------------------------------------------------

def gini(values: list) -> float:
    """Coefficiente di Gini su qualunque serie numerica non negativa
    (granular.gini_degree è il caso particolare values=i degree)."""
    vals = sorted(v for v in values if v is not None)
    n, total = len(vals), sum(v for v in vals)
    if n == 0 or total == 0:
        return 0.0
    cum = sum((i + 1) * v for i, v in enumerate(vals))
    return round((2 * cum) / (n * total) - (n + 1) / n, 4)


def lorenz_curve(values: list) -> pd.DataFrame:
    """Punti della curva di Lorenz: frazione cumulata di popolazione (x)
    vs frazione cumulata del valore (y) — quanto più la curva si allontana
    dalla diagonale, tanto più il valore è concentrato in pochi nodi."""
    vals = sorted(v for v in values if v is not None)
    n, total = len(vals), sum(v for v in vals)
    rows = [{"frazione_popolazione": 0.0, "frazione_valore": 0.0}]
    cum = 0.0
    for i, v in enumerate(vals):
        cum += v
        rows.append({"frazione_popolazione": (i + 1) / n,
                     "frazione_valore": (cum / total) if total else 0.0})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Distribuzione dei gradi (scala log-log)
# ---------------------------------------------------------------------------

def degree_distribution_loglog(G: nx.Graph, weight: str | None = None) -> pd.DataFrame:
    """Distribuzione dei gradi in scala log-log (solo gradi > 0): utile per
    valutare a occhio hub/code pesanti (comportamento scale-free-like)."""
    degrees = [d for _, d in G.degree(weight=weight) if d and d > 0]
    counts = Counter(degrees)
    rows = [{"grado": k, "n_nodi": c, "log_grado": math.log10(k), "log_n_nodi": math.log10(c)}
            for k, c in sorted(counts.items())]
    return pd.DataFrame(rows)
