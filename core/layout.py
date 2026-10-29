"""
layout.py
Calcolo delle posizioni dei nodi per una visualizzazione leggibile.

ForceAtlas2 è nativo in networkx (>=3.4 circa, nx.forceatlas2_layout) e
supporta anche dim=3: non serve più il pacchetto opzionale esterno
`fa2`/`fa2_modified`, usato qui solo come fallback per installazioni con
una networkx più vecchia priva della funzione nativa.
'Yifan Hu' vero e proprio non ha un'implementazione in networkx: il layout
più vicino disponibile qui è kamada_kawai (deterministico, buona
leggibilità su grafi piccoli/medi); per Yifan Hu autentico va esportato il
GEXF e aperto in Gephi.

Le posizioni calcolate vengono messe in CACHE in memoria (chiave = impronta
di nodi+edge+pesi + parametri di layout): richiedere lo stesso layout sulla
stessa rete è immediato, utile in GUI dove ogni anteprima/export ricalcolava
da zero (spring_layout è lento oltre qualche migliaio di nodi). La cache è
trasparente: qualunque modifica a nodi/edge/pesi produce un'impronta diversa
e forza il ricalcolo. Disattivabile con use_cache=False.
"""

from __future__ import annotations

import hashlib

import networkx as nx

_HAS_NATIVE_FA2 = hasattr(nx, "forceatlas2_layout")

if not _HAS_NATIVE_FA2:
    try:
        from fa2_modified import ForceAtlas2
        _HAS_FA2_PKG = True
    except ImportError:
        try:
            from fa2 import ForceAtlas2
            _HAS_FA2_PKG = True
        except ImportError:
            _HAS_FA2_PKG = False
else:
    _HAS_FA2_PKG = False


# ---------------------------------------------------------------------------
# Cache dei layout (in memoria, per sessione)
# ---------------------------------------------------------------------------

_LAYOUT_CACHE: dict[str, dict] = {}
_LAYOUT_CACHE_MAX = 32  # layout tenuti in memoria; oltre, si scarta il più vecchio


def _graph_fingerprint(G: nx.Graph, method: str, seed: int, weight: str | None,
                        extra=None) -> str:
    """
    Impronta stabile del grafo ai fini del layout: dipende da nodi, edge,
    peso degli edge e parametri di calcolo. Gli altri attributi (colori,
    label, metriche) non influenzano le posizioni e sono ignorati.
    `extra` copre i parametri specifici di un metodo (es. level_attr per
    'livelli'), altrimenti layout diversi con parametri diversi
    collisionerebbero sulla stessa chiave di cache.
    """
    nodes = sorted(str(n) for n in G.nodes())
    edges = sorted(
        (min(str(u), str(v)), max(str(u), str(v)),
         str(G[u][v].get(weight)) if weight else "")
        for u, v in G.edges()
    )
    payload = repr((nodes, edges, method, seed, weight, extra))
    return hashlib.sha1(payload.encode()).hexdigest()


def _hierarchical_layout(G: nx.Graph, level_attr: str, level_order: list | None = None) -> dict:
    """
    Layout 'a livelli' (gerarchico/piramidale): raggruppa i nodi per il
    valore di `level_attr` (es. 'ruolo') in fasce orizzontali — una per
    livello — e distribuisce i nodi della fascia sull'asse x. L'ordine dei
    livelli (dall'alto in basso) è `level_order` se dato, altrimenti
    alfabetico. La forma "a piramide" emerge da sola quando i livelli hanno
    numeri di nodi diversi (pochi in cima, molti alla base, o viceversa).
    """
    groups: dict = {}
    for n in G.nodes():
        groups.setdefault(G.nodes[n].get(level_attr), []).append(n)

    order = list(level_order) if level_order else []
    order = [lv for lv in order if lv in groups] + sorted(
        (lv for lv in groups if lv not in order), key=str)

    n_levels = len(order)
    pos = {}
    for i, level in enumerate(order):
        y = 1.0 - (2.0 * i / (n_levels - 1)) if n_levels > 1 else 0.0
        members = sorted(groups[level], key=str)
        m = len(members)
        for j, node in enumerate(members):
            x = 0.0 if m <= 1 else (j / (m - 1) - 0.5) * 2.0
            pos[node] = (x, y)
    return pos


def clear_cache():
    """Svuota la cache dei layout (es. per forzare un ricalcolo con seed diverso)."""
    _LAYOUT_CACHE.clear()


def scale_layout(pos: dict, factor: float) -> dict:
    """
    'Espansione' (factor > 1) / 'Contrazione' (factor < 1) di Gephi: non è
    un algoritmo di layout a sé, ma un riscalamento delle posizioni GIÀ
    calcolate (con qualunque method) rispetto al loro baricentro — utile
    per separare nodi troppo addensati o compattare una rete troppo
    dispersa senza ricalcolare il layout da zero.
    """
    if not pos:
        return pos
    dim = len(next(iter(pos.values())))
    center = [sum(p[i] for p in pos.values()) / len(pos) for i in range(dim)]
    return {n: tuple(center[i] + (p[i] - center[i]) * factor for i in range(dim))
            for n, p in pos.items()}


def compute_layout(G: nx.Graph, method: str = "spring", seed: int = 42,
                    weight: str | None = "weight", use_cache: bool = True,
                    level_attr: str | None = None, level_order: list | None = None,
                    dim: int = 2, **algo_kwargs) -> dict:
    """
    method: 'spring' (default, sempre disponibile), 'fa2' (ForceAtlas2 —
    nativo in networkx, supporta dim=3), 'kamada_kawai' (buono per grafi
    piccoli/medi, più deterministico — l'alternativa più vicina a Yifan Hu
    disponibile qui), 'livelli' (gerarchico/piramidale: richiede level_attr,
    es. 'ruolo' — vedi _hierarchical_layout).
    dim: 2 o 3 (solo per method='fa2'; gli altri metodi restano 2D — vedi
    scale_layout per un post-processing 'espansione/contrazione' applicabile
    a qualunque layout già calcolato).
    algo_kwargs: parametri passati al layout sottostante (stile pannello
    Gephi) — per method='fa2': scaling_ratio, gravity, strong_gravity,
    linlog, max_iter, jitter_tolerance...; per method='spring': k, iterations.
    Ritorna {nodo: (x, y)} (o (x, y, z) con dim=3). Con use_cache=True
    (default) riusa il layout già calcolato per la stessa rete/parametri.
    """
    if G.number_of_nodes() == 0:
        return {}

    if method == "livelli" and not level_attr:
        raise ValueError("method='livelli' richiede level_attr (l'attributo che definisce i livelli).")

    extra = ((level_attr, tuple(level_order) if level_order else None) if method == "livelli"
             else (dim, tuple(sorted(algo_kwargs.items()))))
    key = _graph_fingerprint(G, method, seed, weight, extra=extra) if use_cache else None
    if key is not None and key in _LAYOUT_CACHE:
        return dict(_LAYOUT_CACHE[key])

    if method == "livelli":
        pos = _hierarchical_layout(G, level_attr, level_order)
    elif method == "fa2" and _HAS_NATIVE_FA2:
        params = dict(max_iter=200)
        params.update(algo_kwargs)
        pos = nx.forceatlas2_layout(G, weight=weight, seed=seed, dim=dim, **params)
    elif method == "fa2" and _HAS_FA2_PKG:
        pos = ForceAtlas2(scalingRatio=algo_kwargs.get("scaling_ratio", 2.0),
                           gravity=algo_kwargs.get("gravity", 1.0), verbose=False) \
            .forceatlas2_networkx_layout(G, pos=None, iterations=algo_kwargs.get("max_iter", 200))
    elif method == "kamada_kawai" and G.number_of_nodes() <= 500:
        pos = nx.kamada_kawai_layout(G, weight=weight)
    else:
        # default robusto per qualunque dimensione di rete
        params = dict(weight=weight, seed=seed, iterations=100,
                       k=1 / (G.number_of_nodes() ** 0.5) if G.number_of_nodes() > 0 else None)
        params.update(algo_kwargs)
        pos = nx.spring_layout(G, **params)

    if key is not None:
        if len(_LAYOUT_CACHE) >= _LAYOUT_CACHE_MAX:
            _LAYOUT_CACHE.pop(next(iter(_LAYOUT_CACHE)))  # scarta il più vecchio
        _LAYOUT_CACHE[key] = dict(pos)
    return pos
