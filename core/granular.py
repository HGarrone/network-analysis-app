"""
granular.py
Densità, entropia e metriche di salute della rete a GRANULARITÀ COMPONIBILI:
tutta la rete, una porzione filtrata, per anno, per comunità, per valore di
un attributo (categoria/tipo/ambito), o combinazioni anno×gruppo — scelte
dall'utente. Il risultato è una tabella "lunga" (una riga per gruppo, una
colonna per metrica) pronta per grafici, esportabile in un unico Excel con
foglio dati + tabelle pivot + legenda delle metriche.

Metriche per gruppo (set fisso, dalla letteratura SNA filantropica —
dimensioni Connectivity e Health):
- n_nodi, n_edge, grado_medio
- densita_links_su_nodi (|E|/|V|, definizione del progetto) e
  densita_standard_0_1 (nx.density)
- entropia_vicinato_media — eterogeneità dei vicini di ogni nodo rispetto
  a un attributo (metrics.neighbor_entropy, normalizzata 0-1)
- entropia_composizione — diversità INTERNA del gruppo: entropia di Shannon
  della distribuzione dell'attributo tra i nodi del gruppo, normalizzata
  (0 = tutti della stessa categoria, 1 = equidistribuiti); con n_categorie
  (richness). È la "diversità settoriale" della dimensione Health.
- indice_EI (Krackhardt) — (E−I)/(E+I) sui legami: −1 = tutti interni alla
  stessa categoria (omofilia), +1 = tutti tra categorie diverse (eterofilia)
- clustering_medio — chiusura triadica (fase Growth del ciclo di vita)
- centralizzazione_degree (Freeman) — 1 = stella (dipendenza da un hub),
  0 = gradi tutti uguali; "centralizzazione eccessiva" della letteratura
- gini_degree — concentrazione dei legami (0 = equidistribuiti)
- n_componenti, frazione_componente_maggiore, n_isolati — frammentazione

Granularità (parametro `scopes`, componibile):
- "rete"                       -> una riga su tutto il grafo
- "comunita"                   -> una riga per comunità (louvain/greedy)
- "attributo:<attr>"           -> una riga per valore dell'attributo nodo
                                  (es. "attributo:category")
- "anno"                       -> una riga per anno (snapshot o cumulativo;
                                  serve un grafo con 'anno' sugli edge)
- "anno_x_attributo:<attr>"    -> una riga per (anno, valore attributo)
- "anno_x_comunita"            -> una riga per (anno, comunità di quell'anno)
E in più `custom_filters`: [{"nome": ..., "criteria": {attr: valori},
"keep_neighbors": bool}] -> una riga per ogni sotto-rete filtrata
(criteri stile filters.py, anche su colonne calcolate se presenti sul grafo).
"""

from __future__ import annotations

import math
from collections import Counter

import networkx as nx
import pandas as pd

from . import metrics as metrics_mod
from . import filters, temporal


# ---------------------------------------------------------------------------
# Metriche di gruppo
# ---------------------------------------------------------------------------

def composition_entropy(G: nx.Graph, attribute: str = "category") -> tuple[float, int]:
    """Entropia di Shannon (normalizzata 0-1) della distribuzione
    dell'attributo TRA I NODI del grafo, e numero di valori distinti."""
    counts = Counter(str(G.nodes[n].get(attribute)) for n in G.nodes()
                     if G.nodes[n].get(attribute) is not None)
    k = len(counts)
    if k <= 1:
        return 0.0, k
    ent = metrics_mod.shannon_entropy(list(counts.values()))
    return ent / math.log2(k), k


def ei_index(G: nx.Graph, attribute: str = "category") -> float | None:
    """Indice E-I di Krackhardt: (esterni − interni) / totale legami,
    dove un legame è 'interno' se i due nodi condividono il valore
    dell'attributo. In [−1, 1]; None se il grafo non ha edge."""
    e = i = 0
    for u, v in G.edges():
        a, b = G.nodes[u].get(attribute), G.nodes[v].get(attribute)
        if a is None or b is None:
            continue
        if a == b:
            i += 1
        else:
            e += 1
    tot = e + i
    return round((e - i) / tot, 4) if tot else None


def degree_centralization(G: nx.Graph) -> float:
    """Centralizzazione di Freeman sul degree: 1 = stella, 0 = gradi uguali."""
    n = G.number_of_nodes()
    if n < 3:
        return 0.0
    degrees = [d for _, d in G.degree()]
    dmax = max(degrees)
    return round(sum(dmax - d for d in degrees) / ((n - 1) * (n - 2)), 4)


def gini_degree(G: nx.Graph) -> float:
    """Coefficiente di Gini dei degree (0 = equidistribuiti, ->1 concentrati)."""
    degrees = sorted(d for _, d in G.degree())
    n = len(degrees)
    tot = sum(degrees)
    if n == 0 or tot == 0:
        return 0.0
    cum = sum((i + 1) * d for i, d in enumerate(degrees))
    return round((2 * cum) / (n * tot) - (n + 1) / n, 4)


def group_metrics(G: nx.Graph, entropy_attribute: str = "category") -> dict:
    """Il set completo di metriche per UN gruppo (grafo o sottografo)."""
    n = G.number_of_nodes()
    comp_ent, n_cat = composition_entropy(G, entropy_attribute)
    components = list(nx.connected_components(G)) if n else []
    largest = max((len(c) for c in components), default=0)
    return {
        "n_nodi": n,
        "n_edge": G.number_of_edges(),
        "grado_medio": round(2 * G.number_of_edges() / n, 4) if n else 0.0,
        "densita_links_su_nodi": round(metrics_mod.density_links_over_nodes(G), 4),
        "densita_standard_0_1": round(metrics_mod.density_standard(G), 4),
        "entropia_vicinato_media": round(metrics_mod.average_entropy(G, entropy_attribute), 4),
        "entropia_composizione": round(comp_ent, 4),
        "n_categorie": n_cat,
        "indice_EI": ei_index(G, entropy_attribute),
        "clustering_medio": round(nx.average_clustering(G), 4) if n else 0.0,
        "centralizzazione_degree": degree_centralization(G),
        "gini_degree": gini_degree(G),
        "n_componenti": len(components),
        "frazione_componente_maggiore": round(largest / n, 4) if n else 0.0,
        "n_isolati": len(list(nx.isolates(G))),
    }


# descrizioni per la legenda dell'Excel (e per la GUI)
METRICHE_LEGENDA = {
    "n_nodi": "Numero di nodi del gruppo",
    "n_edge": "Numero di legami del gruppo",
    "grado_medio": "Grado medio (2E/N)",
    "densita_links_su_nodi": "Densità = legami/nodi (definizione del progetto)",
    "densita_standard_0_1": "Densità standard 0-1 (legami / legami possibili)",
    "entropia_vicinato_media": "Eterogeneità media dei vicini (0=omofilo, 1=eterogeneo)",
    "entropia_composizione": "Diversità interna del gruppo per l'attributo scelto (0=una sola categoria)",
    "n_categorie": "Numero di categorie distinte presenti nel gruppo",
    "indice_EI": "Indice E-I di Krackhardt (-1=legami tutti interni alla categoria, +1=tutti tra categorie)",
    "clustering_medio": "Chiusura triadica media (fase Growth del ciclo di vita)",
    "centralizzazione_degree": "Centralizzazione di Freeman (1=stella/dipendenza da un hub)",
    "gini_degree": "Concentrazione dei legami (0=equidistribuiti tra i nodi)",
    "n_componenti": "Numero di componenti connesse",
    "frazione_componente_maggiore": "Quota di nodi nella componente più grande",
    "n_isolati": "Nodi senza alcun legame nel gruppo",
}


# ---------------------------------------------------------------------------
# Granularità
# ---------------------------------------------------------------------------

def _subgraph_by_value(G, attr, value):
    nodes = [n for n in G.nodes() if str(G.nodes[n].get(attr)) == value]
    return G.subgraph(nodes)


def _attr_values(G, attr):
    return sorted({str(G.nodes[n].get(attr)) for n in G.nodes()
                   if G.nodes[n].get(attr) is not None})


def _communities(G, method):
    try:
        return metrics_mod.detect_communities(G, method=method)
    except ImportError:
        return metrics_mod.detect_communities(G, method="greedy_modularity")


def granular_report(G: nx.Graph, scopes: list[str],
                     entropy_attribute: str = "category",
                     community_method: str = "louvain",
                     year_mode: str = "snapshot",
                     custom_filters: list[dict] | None = None,
                     G_temporal: nx.Graph | None = None,
                     manual_selection: list | None = None) -> pd.DataFrame:
    """
    Calcola le metriche di gruppo per ogni granularità richiesta (vedi
    docstring del modulo) e ritorna la tabella lunga con colonne:
    granularita, gruppo, anno, + tutte le metriche.
    G_temporal: grafo con 'anno' sugli edge per le granularità per anno
    (default: G stesso — tipicamente il bipartito).
    manual_selection: lista di nodi per lo scope 'selezione_manuale' — una
    'zona' scelta a mano (es. un sottoinsieme di nodi selezionati in tabella),
    non necessariamente una categoria o comunità esistente.
    """
    GT = G_temporal if G_temporal is not None else G
    rows = []

    def add(granularita, gruppo, anno, H):
        rows.append({"granularita": granularita, "gruppo": gruppo, "anno": anno,
                      **group_metrics(H, entropy_attribute)})

    for scope in scopes:
        if scope == "rete":
            add("rete", "tutta la rete", None, G)

        elif scope == "comunita":
            partition = _communities(G, community_method)
            comms: dict = {}
            for node, cid in partition.items():
                comms.setdefault(cid, []).append(node)
            for cid, nodes in sorted(comms.items()):
                add("comunita", f"comunita_{cid}", None, G.subgraph(nodes))

        elif scope.startswith("attributo:"):
            attr = scope.split(":", 1)[1]
            for value in _attr_values(G, attr):
                add(f"attributo:{attr}", value, None, _subgraph_by_value(G, attr, value))

        elif scope == "anno":
            for y, Gy in sorted(temporal.split_by_year(GT, mode=year_mode).items()):
                add(f"anno ({year_mode})", "tutta la rete", y, Gy)

        elif scope.startswith("anno_x_attributo:"):
            attr = scope.split(":", 1)[1]
            for y, Gy in sorted(temporal.split_by_year(GT, mode=year_mode).items()):
                for value in _attr_values(Gy, attr):
                    add(f"anno_x_attributo:{attr}", value, y,
                        _subgraph_by_value(Gy, attr, value))

        elif scope == "selezione_manuale":
            if not manual_selection:
                raise ValueError("Serve 'manual_selection' (lista di nodi) per lo scope 'selezione_manuale'.")
            add("selezione_manuale", f"{len(manual_selection)} nodi scelti", None,
                G.subgraph(manual_selection))

        elif scope == "anno_x_comunita":
            for y, Gy in sorted(temporal.split_by_year(GT, mode=year_mode).items()):
                partition = _communities(Gy, community_method)
                comms = {}
                for node, cid in partition.items():
                    comms.setdefault(cid, []).append(node)
                for cid, nodes in sorted(comms.items()):
                    add("anno_x_comunita", f"comunita_{cid}", y, Gy.subgraph(nodes))

        else:
            raise ValueError(f"Granularità '{scope}' non riconosciuta.")

    for f in custom_filters or []:
        sub = filters.build_subgraph(G, f["criteria"],
                                      keep_neighbors=f.get("keep_neighbors", False))
        add("filtro", f.get("nome") or str(f["criteria"]), None, sub)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Export Excel (foglio dati + pivot per grafici + legenda)
# ---------------------------------------------------------------------------

def export_granular_excel(df: pd.DataFrame, path: str,
                            pivot_metrics: tuple = ("densita_links_su_nodi",
                                                     "entropia_vicinato_media",
                                                     "entropia_composizione")) -> str:
    """
    Un unico .xlsx comodo per i grafici:
    - foglio 'dati': la tabella lunga (una riga per gruppo/anno);
    - un foglio pivot per ognuna delle pivot_metrics presenti, con righe =
      gruppo e colonne = anno (solo se ci sono granularità per anno);
    - foglio 'legenda' con la spiegazione di ogni metrica.
    """
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="dati", index=False)

        con_anno = df[df["anno"].notna()] if "anno" in df.columns else pd.DataFrame()
        for metrica in pivot_metrics:
            if metrica not in df.columns or con_anno.empty:
                continue
            pivot = con_anno.pivot_table(index=["granularita", "gruppo"],
                                          columns="anno", values=metrica,
                                          aggfunc="first")
            nome = f"pivot_{metrica}"[:31]  # limite nome foglio Excel
            pivot.to_excel(writer, sheet_name=nome)

        legenda = pd.DataFrame(
            [{"metrica": k, "descrizione": v} for k, v in METRICHE_LEGENDA.items()])
        legenda.to_excel(writer, sheet_name="legenda", index=False)
    return path
