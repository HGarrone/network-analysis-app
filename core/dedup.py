"""
dedup.py
Pulizia dei nodi con nomi "sporchi": individuazione di label molto simili
(che probabilmente sono lo stesso ente scritto in modi diversi), fusione
dei nodi duplicati e rinomina di ID/label.

- `find_similar_labels(G)` — gruppi di nodi con label quasi uguali
  (normalizzazione accenti/punteggiatura/maiuscole + similarità di
  sequenza e di insieme di parole). Da usare subito dopo l'import per
  rivedere i probabili duplicati.
- `merge_nodes(G, keep, merge_ids)` — fonde i nodi duplicati in uno solo:
  gli edge vengono riattaccati al nodo mantenuto (pesi sommati sugli edge
  che collidono, liste `records` concatenate) e gli ATTRIBUTI vengono
  ereditati tutti: se i valori differiscono, vengono uniti in un'unica
  stringa separata da ", " (regola valida per qualunque colonna originale
  dell'Excel).
- `rename_node(G, old_id, new_id, new_label)` — corregge ID e/o label di
  un nodo (utile quando il nome è sporco ma il nodo è unico).
- `merge_attr_dicts(dicts)` — la regola di eredità ", " riutilizzabile
  (usata anche dal coarse-graining per conservare le colonne originali).

Tutte le funzioni di modifica ritornano un grafo NUOVO (stile pipeline).
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

import networkx as nx


# ---------------------------------------------------------------------------
# Normalizzazione e similarità
# ---------------------------------------------------------------------------

def normalize_label(s) -> str:
    """minuscole, senza accenti, senza punteggiatura, spazi collassati."""
    s = str(s or "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def label_similarity(a, b) -> float:
    """
    Similarità in [0,1] tra due label: il massimo tra la similarità di
    sequenza (SequenceMatcher) e quella calcolata sulle parole ordinate
    (così "Fondazione ABC" ~ "ABC Fondazione").
    """
    na, nb = normalize_label(a), normalize_label(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    tok = SequenceMatcher(None, " ".join(sorted(na.split())),
                           " ".join(sorted(nb.split()))).ratio()
    return max(seq, tok)


def find_similar_labels(G: nx.Graph, threshold: float = 0.85,
                         attr: str = "label", scope_attr: str | None = "bipartite") -> list[dict]:
    """
    Trova i gruppi di nodi con label simili sopra la soglia. Con scope_attr
    (default 'bipartite') confronta solo nodi dello stesso lato (un ente non
    viene mai proposto come duplicato di un progetto).
    Ritorna una lista di gruppi ordinati per similarità decrescente:
      [{"nodi": [(id, label), ...], "similarita_min": 0.9}, ...]
    """
    nodes = [(n, str(G.nodes[n].get(attr, n))) for n in G.nodes()]
    # prefiltro: normalizzati identici o quick_ratio alto
    parent = {n: n for n, _ in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    pair_scores: dict = {}
    for i in range(len(nodes)):
        ni, li = nodes[i]
        for j in range(i + 1, len(nodes)):
            nj, lj = nodes[j]
            if scope_attr and G.nodes[ni].get(scope_attr) != G.nodes[nj].get(scope_attr):
                continue
            # prefiltro veloce prima del ratio completo
            if SequenceMatcher(None, normalize_label(li), normalize_label(lj)).quick_ratio() < threshold:
                continue
            score = label_similarity(li, lj)
            if score >= threshold:
                union(ni, nj)
                pair_scores[(ni, nj)] = score

    groups: dict = {}
    for n, lab in nodes:
        groups.setdefault(find(n), []).append((n, lab))
    result = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ids = {m[0] for m in members}
        scores = [s for (a, b), s in pair_scores.items() if a in ids and b in ids]
        result.append({"nodi": sorted(members, key=lambda t: t[1]),
                        "similarita_min": round(min(scores), 3) if scores else threshold})
    return sorted(result, key=lambda g: -g["similarita_min"])


# ---------------------------------------------------------------------------
# Eredità degli attributi (regola ", ")
# ---------------------------------------------------------------------------

def merge_attr_dicts(dicts: list[dict], skip_prefixes: tuple = ("viz_",),
                      skip_keys: tuple = ()) -> dict:
    """
    Fonde più dizionari di attributi: se un attributo ha lo stesso valore
    ovunque lo mantiene com'è (tipo compreso); se i valori differiscono li
    eredita TUTTI in un'unica stringa separata da ", " (unici, in ordine).
    Le liste (es. anni, records) vengono concatenate senza duplicati.
    """
    merged: dict = {}
    keys: list = []
    for d in dicts:
        for k in d:
            if k not in keys:
                keys.append(k)
    for k in keys:
        if k in skip_keys or any(k.startswith(p) for p in skip_prefixes):
            continue
        values = [d[k] for d in dicts if k in d and d[k] is not None]
        if not values:
            merged[k] = None
            continue
        if all(isinstance(v, list) for v in values):
            out = []
            for lst in values:
                for x in lst:
                    if x not in out:
                        out.append(x)
            merged[k] = out
            continue
        distinct = []
        for v in values:
            s = str(v)
            if s not in distinct:
                distinct.append(s)
        merged[k] = values[0] if len(distinct) == 1 else ", ".join(distinct)
    return merged


# ---------------------------------------------------------------------------
# Fusione e rinomina
# ---------------------------------------------------------------------------

def merge_nodes(G: nx.Graph, keep, merge_ids: list, new_label: str | None = None) -> nx.Graph:
    """
    Fonde i nodi di merge_ids nel nodo `keep` (grafo NUOVO):
    - attributi: eredità con la regola ", " (merge_attr_dicts);
    - edge dei nodi fusi riattaccati a keep; se l'edge esiste già, i pesi
      si sommano, le liste `records` si concatenano e gli altri attributi
      seguono la regola ", "; gli edge tra i nodi fusi diventano self-loop
      e vengono scartati.
    new_label (opzionale) sostituisce la label del nodo risultante.
    """
    merge_ids = [m for m in merge_ids if m in G and m != keep]
    if keep not in G:
        raise ValueError(f"Nodo da mantenere '{keep}' non presente nel grafo.")
    H = G.copy()
    group = {keep, *merge_ids}
    H.nodes[keep].update(merge_attr_dicts([G.nodes[keep]] + [G.nodes[m] for m in merge_ids]))

    for m in merge_ids:
        for nbr in list(H.neighbors(m)):
            if nbr in group:
                continue  # diventerebbe un self-loop
            attrs = dict(H[m][nbr])
            if H.has_edge(keep, nbr):
                e = H[keep][nbr]
                combined = merge_attr_dicts([dict(e), attrs])
                combined["weight"] = (e.get("weight", 1) or 1) + (attrs.get("weight", 1) or 1)
                e.clear()
                e.update(combined)
            else:
                H.add_edge(keep, nbr, **attrs)
        H.remove_node(m)

    if new_label is not None:
        H.nodes[keep]["label"] = new_label
    return H


def rename_node(G: nx.Graph, old_id, new_id=None, new_label: str | None = None) -> nx.Graph:
    """
    Corregge l'ID e/o la label di un nodo (grafo NUOVO). Se new_id esiste
    già nel grafo, solleva errore: per unire due nodi usare merge_nodes.
    """
    if old_id not in G:
        raise ValueError(f"Nodo '{old_id}' non presente nel grafo.")
    if new_id is not None and new_id != old_id and new_id in G:
        raise ValueError(f"ID '{new_id}' già esistente: per fondere i due nodi usa merge_nodes.")
    H = nx.relabel_nodes(G, {old_id: new_id}, copy=True) if new_id and new_id != old_id else G.copy()
    target = new_id if new_id and new_id != old_id else old_id
    if new_label is not None:
        H.nodes[target]["label"] = new_label
    return H
