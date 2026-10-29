"""
metrics.py
Metriche strutturali richieste: community detection, degree, diametro,
entropia (eterogeneità dei vicini), densità (sia la definizione "links/nodi"
usata dall'utente, sia la densità standard di networkx per confronto).
"""

from __future__ import annotations

import math
from collections import Counter

import networkx as nx

try:
    import community as community_louvain  # python-louvain
    _HAS_LOUVAIN = True
except ImportError:
    _HAS_LOUVAIN = False


# ---------------------------------------------------------------------------
# Densità
# ---------------------------------------------------------------------------

def density_links_over_nodes(G: nx.Graph) -> float:
    """Definizione usata nel brief dell'utente: densità = |E| / |V|."""
    n = G.number_of_nodes()
    if n == 0:
        return 0.0
    return G.number_of_edges() / n


def density_standard(G: nx.Graph) -> float:
    """Densità standard (0-1): |E| / |E_max possibili|. Utile come confronto/normalizzazione."""
    return nx.density(G)


def density_report(G: nx.Graph) -> dict:
    return {
        "n_nodi": G.number_of_nodes(),
        "n_edge": G.number_of_edges(),
        "densita_links_su_nodi": density_links_over_nodes(G),
        "densita_standard_0_1": density_standard(G),
    }


# ---------------------------------------------------------------------------
# Degree
# ---------------------------------------------------------------------------

def degree_stats(G: nx.Graph, weight: str | None = None) -> dict:
    degrees = dict(G.degree(weight=weight))
    if not degrees:
        return {"per_nodo": {}, "media": 0, "mediana": 0, "max": None, "min": None}
    values = sorted(degrees.values())
    n = len(values)
    mediana = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
    top_node = max(degrees, key=degrees.get)
    return {
        "per_nodo": degrees,
        "media": sum(values) / n,
        "mediana": mediana,
        "max": (top_node, degrees[top_node]),
        "min_valore": min(values),
    }


# ---------------------------------------------------------------------------
# Betweenness (broker/ponti strutturali tra cluster, brief §1.4)
# ---------------------------------------------------------------------------

def betweenness_centrality(G: nx.Graph, normalized: bool = True,
                            weight: str | None = None) -> dict:
    """
    Betweenness per nodo: quota di cammini minimi che passano dal nodo.
    Identifica i broker/ponti tra sotto-gruppi (valore alto = il nodo
    connette parti della rete altrimenti lontane). Con weight, i cammini
    minimi usano la DISTANZA = attributo indicato: attenzione che qui i
    pesi sono "forze" (più alto = legame più forte), quindi il default è
    non pesato; per pesare servirebbe una trasformazione 1/weight.
    """
    return nx.betweenness_centrality(G, normalized=normalized, weight=weight)


# ---------------------------------------------------------------------------
# Clustering (fase del ciclo di vita del network, brief §1.6)
# ---------------------------------------------------------------------------

def clustering_report(G: nx.Graph) -> dict:
    """
    Clustering medio e transitività globale: quanto i vicini di un nodo
    sono connessi tra loro (chiusura triadica). Indicatore della fase
    Growth/Maturity del ciclo di vita del network. NOTA: sul grafo
    bipartito è strutturalmente 0 (niente triangoli): ha senso sulle
    proiezioni Ente-Ente / Progetto-Progetto.
    """
    if G.number_of_nodes() == 0:
        return {"clustering_medio": 0.0, "transitivita": 0.0}
    return {
        "clustering_medio": nx.average_clustering(G),
        "transitivita": nx.transitivity(G),
    }


# ---------------------------------------------------------------------------
# Diametro / connettività
# ---------------------------------------------------------------------------

def diameter_report(G: nx.Graph) -> dict:
    """
    Il diametro è definito solo su grafi connessi: se il grafo è disconnesso
    (molto probabile qui) calcoliamo il diametro della componente connessa
    più grande e riportiamo anche il numero di componenti.
    """
    components = list(nx.connected_components(G))
    n_components = len(components)
    if n_components == 0:
        return {"diametro_componente_maggiore": None, "n_componenti": 0, "dim_componente_maggiore": 0}
    largest = max(components, key=len)
    sub = G.subgraph(largest)
    try:
        diam = nx.diameter(sub)
        avg_path = nx.average_shortest_path_length(sub)
    except nx.NetworkXError:
        diam, avg_path = None, None
    return {
        "diametro_componente_maggiore": diam,
        "cammino_medio_componente_maggiore": avg_path,
        "n_componenti": n_components,
        "dim_componente_maggiore": len(largest),
    }


# ---------------------------------------------------------------------------
# Entropia di vicinato (eterogeneità dei vicini rispetto a un attributo)
# ---------------------------------------------------------------------------

def shannon_entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total == 0:
        return 0.0
    ent = 0.0
    for c in counts:
        if c == 0:
            continue
        p = c / total
        ent -= p * math.log2(p)
    return ent


def neighbor_entropy(G: nx.Graph, attribute: str = "category", normalize: bool = True) -> dict:
    """
    Per ogni nodo, calcola l'entropia di Shannon della distribuzione
    dell'attributo scelto (es. 'category') tra i suoi vicini diretti.
    Un nodo con vicini tutti della stessa categoria ha entropia 0
    (rete "omofila" localmente); un nodo con vicini equidistribuiti su molte
    categorie ha entropia alta (rete localmente eterogenea/di ponte).
    Se normalize=True, l'entropia viene divisa per log2(k) (k = categorie
    distinte presenti nel grafo) per ottenere un valore in [0, 1] confrontabile
    tra nodi con numero di vicini diverso.
    """
    all_values = {G.nodes[n].get(attribute) for n in G.nodes()}
    all_values.discard(None)
    k = max(len(all_values), 1)

    result = {}
    for n in G.nodes():
        neighbors = list(G.neighbors(n))
        if not neighbors:
            result[n] = 0.0
            continue
        counts = Counter(G.nodes[nb].get(attribute) for nb in neighbors)
        ent = shannon_entropy(list(counts.values()))
        if normalize and k > 1:
            ent = ent / math.log2(k)
        result[n] = ent
    return result


def average_entropy(G: nx.Graph, attribute: str = "category", normalize: bool = True) -> float:
    values = neighbor_entropy(G, attribute, normalize)
    if not values:
        return 0.0
    return sum(values.values()) / len(values)


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------

def detect_communities(G: nx.Graph, method: str = "louvain", weight: str = "weight") -> dict:
    """
    Ritorna {nodo: id_comunita}.
    method:
      - 'louvain'  (richiede python-louvain; default, migliore qualità generale)
      - 'greedy_modularity' (fallback nativo di networkx, nessuna dipendenza extra)
      - 'label_propagation' (veloce, utile per grafi molto grandi)
    """
    if G.number_of_nodes() == 0:
        return {}

    if method == "louvain":
        if not _HAS_LOUVAIN:
            raise ImportError("python-louvain non installato: usa method='greedy_modularity'.")
        return community_louvain.best_partition(G, weight=weight)

    if method == "greedy_modularity":
        comms = nx.algorithms.community.greedy_modularity_communities(G, weight=weight)
        return {n: i for i, comm in enumerate(comms) for n in comm}

    if method == "label_propagation":
        comms = nx.algorithms.community.label_propagation_communities(G)
        return {n: i for i, comm in enumerate(comms) for n in comm}

    raise ValueError(f"Metodo di community detection non riconosciuto: {method}")


def modularity(G: nx.Graph, partition: dict, weight: str = "weight") -> float:
    """Calcola la modularità di una partizione (qualità della suddivisione in comunità)."""
    comms = {}
    for node, comm_id in partition.items():
        comms.setdefault(comm_id, set()).add(node)
    return nx.algorithms.community.modularity(G, comms.values(), weight=weight)


# ---------------------------------------------------------------------------
# Metriche per comunità (densità/entropia ristrette a ogni comunità, brief §3.3)
# ---------------------------------------------------------------------------

def per_community_report(G: nx.Graph, partition: dict,
                          entropy_attribute: str = "category") -> dict:
    """
    Per ogni comunità della partizione, le metriche calcolate sul sottografo
    indotto dai suoi nodi: {id_comunita: {n_nodi, n_edge, densità (entrambe),
    entropia_media}}. Utile per capire quali comunità si addensano/rarefanno
    e quanto sono internamente eterogenee.
    """
    comms: dict = {}
    for node, comm_id in partition.items():
        comms.setdefault(comm_id, []).append(node)
    result = {}
    for comm_id, nodes in sorted(comms.items(), key=lambda kv: -len(kv[1])):
        sub = G.subgraph(nodes)
        result[comm_id] = {
            **density_report(sub),
            "entropia_media": average_entropy(sub, entropy_attribute),
        }
    return result


# ---------------------------------------------------------------------------
# Riepilogo unico (comodo per il report)
# ---------------------------------------------------------------------------

def full_metrics_report(G: nx.Graph, entropy_attribute: str = "category",
                         community_method: str = "louvain") -> dict:
    partition = detect_communities(G, method=community_method)
    return {
        "densita": density_report(G),
        "degree": degree_stats(G),
        "degree_pesato": degree_stats(G, weight="weight"),
        "betweenness_per_nodo": betweenness_centrality(G),
        "clustering": clustering_report(G),
        "diametro": diameter_report(G),
        "entropia_media": average_entropy(G, entropy_attribute),
        "entropia_per_nodo": neighbor_entropy(G, entropy_attribute),
        "comunita": partition,
        "n_comunita": len(set(partition.values())) if partition else 0,
        "modularita": modularity(G, partition) if partition else None,
        "per_comunita": per_community_report(G, partition, entropy_attribute) if partition else {},
    }
