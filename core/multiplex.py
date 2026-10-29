"""
multiplex.py
Reti multiplex: più tipi di legame (layer) tra gli stessi nodi, con
selezione/sovrapposizione dei layer e strategie di risoluzione degli edge
paralleli in stile Gephi.

Rappresentazione: un nx.MultiGraph dove
- ogni edge porta l'attributo `layer` (più edge paralleli tra gli stessi
  due nodi, anche nello stesso layer, sono ammessi);
- ogni nodo porta l'attributo `layers` = lista dei layer in cui compare
  (ricalcolata da update_node_layers), così un nodo può "stare" su più
  layer e la selezione dei layer sa quali nodi includere.

Tre modi per costruire i layer:
- `build_multiplex(G, layer_by="anno")` — divide gli edge di un grafo
  esistente per un attributo (es. anno → un layer per anno). Sul bipartito
  Ente-Progetto espande anche `records` (le multi-relazioni accumulate da
  data_io), quindi con layer_by="interaction_type" ogni relazione
  Partner/Capofila/Cofinanziatore finisce nel proprio layer anche quando
  condivide la coppia ente-progetto con altre.
- `add_layer(M, G_layer, "nome")` — sovrappone un intero grafo come nuovo
  layer (es. la proiezione ente-ente come layer sopra la rete bipartita
  totale, tenendo tutto nello stesso oggetto).
- combinazione dei due: si parte da build_multiplex e si aggiungono layer.

Composizione: `flatten(M, layers, strategy, merge_scope)` seleziona i layer
scelti e risolve gli edge paralleli:
- strategy (come in Gephi): 'sum', 'mean', 'max', 'min', 'count',
  'first', 'last' — applicata al peso.
- merge_scope:
  - 'all'          -> unisce tutto: un solo edge per coppia di nodi,
                      anche tra layer diversi (ritorna nx.Graph)
  - 'within_layer' -> "non unire tra layer diversi": unisce i paralleli
                      dentro ogni layer ma tiene un edge per layer
                      (ritorna nx.MultiGraph con attributo layer)
  - 'none'         -> "non unire mai": mantiene tutti gli edge paralleli
                      (ritorna nx.MultiGraph)
NB: molte analisi (louvain, proiezioni, ...) richiedono un grafo semplice:
usare merge_scope='all' prima di passarle il risultato.
"""

from __future__ import annotations

import statistics

import networkx as nx

# Strategie di risoluzione degli edge paralleli (applicate al peso), come Gephi.
MERGE_STRATEGIES = {
    "sum": sum,
    "mean": lambda vals: statistics.mean(vals),
    "max": max,
    "min": min,
    "count": len,
    "first": lambda vals: vals[0],
    "last": lambda vals: vals[-1],
}

MERGE_SCOPES = ("all", "within_layer", "none")


# ---------------------------------------------------------------------------
# Costruzione
# ---------------------------------------------------------------------------

def update_node_layers(M: nx.MultiGraph) -> nx.MultiGraph:
    """Ricalcola l'attributo `layers` di ogni nodo dai layer dei suoi edge."""
    node_layers: dict = {n: set() for n in M.nodes()}
    for u, v, d in M.edges(data=True):
        layer = str(d.get("layer"))
        node_layers[u].add(layer)
        node_layers[v].add(layer)
    for n, ls in node_layers.items():
        M.nodes[n]["layers"] = sorted(ls)
    return M


def build_multiplex(G: nx.Graph, layer_by: str = "anno",
                     expand_records: bool = True,
                     records_attr: str = "records") -> nx.MultiGraph:
    """
    Costruisce il multiplex dividendo gli edge di G per il valore di un
    attributo (layer_by): es. 'anno' -> un layer per anno,
    'interaction_type' -> un layer per tipo di relazione.
    Con expand_records=True (default), se un edge porta la lista `records`
    delle multi-relazioni (vedi data_io), OGNI record diventa un edge nel
    layer del suo valore — senza perdere le relazioni accorpate.
    Gli edge privi dell'attributo finiscono nel layer 'senza_layer'.
    """
    M = nx.MultiGraph()
    M.add_nodes_from(G.nodes(data=True))
    for u, v, attrs in G.edges(data=True):
        records = attrs.get(records_attr) if expand_records else None
        if records:
            for rec in records:
                layer = rec.get(layer_by, attrs.get(layer_by))
                M.add_edge(u, v, layer=str(layer if layer is not None else "senza_layer"),
                           **{k: w for k, w in rec.items()})
        else:
            base = {k: w for k, w in attrs.items() if k != records_attr}
            layer = base.pop(layer_by, None)
            M.add_edge(u, v, layer=str(layer if layer is not None else "senza_layer"), **base)
    return update_node_layers(M)


def add_layer(M: nx.MultiGraph | None, G_layer: nx.Graph, layer_name: str,
               replace: bool = False) -> nx.MultiGraph:
    """
    Sovrappone G_layer come nuovo layer (es. una proiezione ente-ente sopra
    il multiplex della rete totale). I nodi nuovi vengono aggiunti con i loro
    attributi; per i nodi già presenti gli attributi esistenti non vengono
    sovrascritti. Con M=None crea un multiplex nuovo.
    replace=True rimuove prima gli edge di un eventuale layer omonimo.
    """
    if M is None:
        M = nx.MultiGraph()
    layer_name = str(layer_name)
    if replace:
        remove_layer(M, layer_name)
    elif layer_name in get_layers(M):
        raise ValueError(f"Layer '{layer_name}' già presente: usa replace=True "
                         "per sostituirlo o scegli un altro nome.")
    for n, attrs in G_layer.nodes(data=True):
        if n not in M:
            M.add_node(n, **attrs)
        else:
            for k, w in attrs.items():
                M.nodes[n].setdefault(k, w)
    for u, v, attrs in G_layer.edges(data=True):
        base = {k: w for k, w in attrs.items() if k != "layer"}
        M.add_edge(u, v, layer=layer_name, **base)
    return update_node_layers(M)


def remove_layer(M: nx.MultiGraph, layer_name: str) -> nx.MultiGraph:
    """Rimuove tutti gli edge del layer indicato (i nodi restano)."""
    to_remove = [(u, v, k) for u, v, k, d in M.edges(keys=True, data=True)
                 if str(d.get("layer")) == str(layer_name)]
    M.remove_edges_from(to_remove)
    return update_node_layers(M)


# ---------------------------------------------------------------------------
# Ispezione
# ---------------------------------------------------------------------------

def get_layers(M: nx.MultiGraph) -> list[str]:
    """Nomi dei layer presenti, ordinati."""
    return sorted({str(d.get("layer")) for _, _, d in M.edges(data=True)})


def layer_summary(M: nx.MultiGraph) -> list[dict]:
    """Una riga per layer: nome, numero di nodi toccati, numero di edge."""
    rows = []
    for layer in get_layers(M):
        nodes = set()
        n_edges = 0
        for u, v, d in M.edges(data=True):
            if str(d.get("layer")) == layer:
                nodes.update((u, v))
                n_edges += 1
        rows.append({"layer": layer, "n_nodi": len(nodes), "n_edge": n_edges})
    return rows


# ---------------------------------------------------------------------------
# Selezione layer e composizione (flatten)
# ---------------------------------------------------------------------------

def flatten(M: nx.MultiGraph, layers: list | None = None, strategy: str = "sum",
             merge_scope: str = "all", include_isolated: bool = False):
    """
    Compone una rete dai layer selezionati (None = tutti), risolvendo gli
    edge paralleli secondo strategy e merge_scope (vedi docstring modulo).
    Ogni edge risultante porta: weight (secondo la strategia), n_merged
    (quanti edge originali riassume), layers (da quali layer proviene) e
    gli altri attributi del primo edge del gruppo ('first'/'last' seguono
    l'ordine di inserimento nel multiplex).
    include_isolated=True include anche i nodi dei layer selezionati
    rimasti senza edge dopo la selezione.
    """
    if strategy not in MERGE_STRATEGIES:
        raise ValueError(f"Strategia '{strategy}' non riconosciuta. "
                         f"Disponibili: {list(MERGE_STRATEGIES)}")
    if merge_scope not in MERGE_SCOPES:
        raise ValueError(f"merge_scope '{merge_scope}' non riconosciuto. "
                         f"Disponibili: {list(MERGE_SCOPES)}")
    selected = set(map(str, layers)) if layers is not None else None

    def _in_selection(d):
        return selected is None or str(d.get("layer")) in selected

    edges = [(u, v, d) for u, v, d in M.edges(data=True) if _in_selection(d)]

    if merge_scope == "none":
        H = nx.MultiGraph()
        for u, v, d in edges:
            H.add_edge(u, v, **d)
    else:
        groups: dict = {}
        for u, v, d in edges:
            a, b = (u, v) if str(u) <= str(v) else (v, u)
            key = (a, b, str(d.get("layer"))) if merge_scope == "within_layer" else (a, b)
            groups.setdefault(key, []).append(d)
        H = nx.MultiGraph() if merge_scope == "within_layer" else nx.Graph()
        for key, ds in groups.items():
            a, b = key[0], key[1]
            attrs = dict(ds[0])
            attrs["weight"] = MERGE_STRATEGIES[strategy]([d.get("weight", 1) for d in ds])
            attrs["n_merged"] = len(ds)
            attrs["layers"] = sorted({str(d.get("layer")) for d in ds})
            if merge_scope == "all":
                attrs.pop("layer", None)
            H.add_edge(a, b, **attrs)

    # riporta gli attributi dei nodi coinvolti (e opzionalmente gli isolati)
    for n in list(H.nodes()):
        H.nodes[n].update(M.nodes[n])
    if include_isolated:
        for n, attrs in M.nodes(data=True):
            node_layers = set(attrs.get("layers", []))
            if n not in H and (selected is None or node_layers & selected):
                H.add_node(n, **attrs)
    return H


def layer_graph(M: nx.MultiGraph, layer: str, strategy: str = "sum") -> nx.Graph:
    """Scorciatoia: un singolo layer come grafo semplice (paralleli uniti)."""
    return flatten(M, layers=[layer], strategy=strategy, merge_scope="all")


# ---------------------------------------------------------------------------
# Metriche multiplex (cross-layer)
# ---------------------------------------------------------------------------

def pair_layers(M: nx.MultiGraph) -> dict:
    """{(u, v): set di layer} per ogni coppia di nodi collegata (non orientata)."""
    result: dict = {}
    for u, v, d in M.edges(data=True):
        key = (u, v) if str(u) <= str(v) else (v, u)
        result.setdefault(key, set()).add(str(d.get("layer")))
    return result


def multiplexity_report(M: nx.MultiGraph) -> dict:
    """
    Quanto le relazioni sono multiplex (brief §1.1): coppie collegate su
    più layer contemporaneamente. Ritorna:
      - n_coppie, n_coppie_multiplex (>= 2 layer), frazione_multiplex
      - distribuzione {n_layer: n_coppie}
      - coppie_multiplex: righe {u, v, label_u, label_v, n_layer, layers}
        ordinate per numero di layer decrescente (pronte per DataFrame)
    """
    pl = pair_layers(M)
    dist: dict = {}
    rows = []
    for (u, v), layers in pl.items():
        dist[len(layers)] = dist.get(len(layers), 0) + 1
        if len(layers) >= 2:
            rows.append({"u": u, "v": v,
                          "label_u": M.nodes[u].get("label", u),
                          "label_v": M.nodes[v].get("label", v),
                          "n_layer": len(layers), "layers": ", ".join(sorted(layers))})
    rows.sort(key=lambda r: -r["n_layer"])
    n_multi = len(rows)
    return {"n_coppie": len(pl), "n_coppie_multiplex": n_multi,
            "frazione_multiplex": round(n_multi / len(pl), 3) if pl else 0.0,
            "distribuzione": dict(sorted(dist.items())),
            "coppie_multiplex": rows}


def layer_overlap(M: nx.MultiGraph) -> list[dict]:
    """
    Sovrapposizione tra ogni coppia di layer: indice di Jaccard sulle coppie
    di nodi collegate (1 = i due layer collegano le stesse coppie).
    Righe {layer_a, layer_b, coppie_comuni, jaccard}.
    """
    pl = pair_layers(M)
    by_layer: dict = {}
    for pair, layers in pl.items():
        for l in layers:
            by_layer.setdefault(l, set()).add(pair)
    names = sorted(by_layer)
    rows = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = by_layer[names[i]], by_layer[names[j]]
            union = a | b
            rows.append({"layer_a": names[i], "layer_b": names[j],
                          "coppie_comuni": len(a & b),
                          "jaccard": round(len(a & b) / len(union), 3) if union else 0.0})
    return sorted(rows, key=lambda r: -r["jaccard"])


def intensity_levels(M: nx.MultiGraph, levels: list[str]) -> dict:
    """
    Lettura dei livelli CUMULATIVI di intensità del legame (brief §1.1:
    scambio informazioni -> coordinamento -> collaborazione -> co-finanziamento).
    `levels` è la lista ordinata dal livello più debole al più forte, con i
    NOMI DEI LAYER (es. ["Partner", "Ente capofila", "Cofinanziatore"]).
    Per ogni coppia collegata: livello massimo raggiunto. Ritorna
    {per_coppia: righe, conteggio_per_livello: {livello: n_coppie}}.
    """
    idx = {str(l): i for i, l in enumerate(levels)}
    rows = []
    counts = {str(l): 0 for l in levels}
    for (u, v), layers in pair_layers(M).items():
        known = [l for l in layers if l in idx]
        if not known:
            continue
        top = max(known, key=lambda l: idx[l])
        counts[top] += 1
        rows.append({"u": u, "v": v,
                      "label_u": M.nodes[u].get("label", u),
                      "label_v": M.nodes[v].get("label", v),
                      "livello_massimo": top, "livelli_presenti": ", ".join(sorted(known))})
    rows.sort(key=lambda r: -idx[r["livello_massimo"]])
    return {"per_coppia": rows, "conteggio_per_livello": counts, "ordine_livelli": [str(l) for l in levels]}
