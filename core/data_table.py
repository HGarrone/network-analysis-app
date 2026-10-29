"""
data_table.py
Vista tabellare del grafo in stile "Data Laboratory" di Gephi: una riga per
nodo (o per edge), una colonna per attributo — inclusi gli attributi calcolati
a runtime dalla pipeline (degree, degree pesato, entropia di vicinato,
comunità), non solo quelli originari da Excel.

Tre blocchi di funzioni:

1. COSTRUZIONE TABELLA: `add_computed_columns` scrive le metriche calcolate
   come attributi dei nodi (così restano sul grafo e finiscono anche negli
   export GEXF/GraphML/CSV); `nodes_table` / `edges_table` costruiscono il
   DataFrame pandas della rete corrente.

2. ORDINAMENTO E SELEZIONE PER CONDIZIONE: `sort_table` ordina per qualsiasi
   colonna (numerica o categoriale); `select_ids_by_conditions` valuta una
   lista di condizioni (colonna, operatore, valore) sulle colonne della
   tabella — comprese quelle calcolate — e restituisce gli id dei nodi
   selezionati. Le condizioni sono tuple, es. ("degree", "==", 0) oppure
   ("category", "==", "Cultura").

3. CANCELLAZIONE: `remove_nodes` è il negativo di filters.build_subgraph —
   costruisce un NUOVO grafo senza i nodi indicati (e senza gli edge
   incidenti), lasciando intatto il grafo di partenza. `remove_by_conditions`
   combina selezione + rimozione in un passo solo (es. elimina tutti i nodi
   con degree == 0). È una modifica di SELEZIONE (rete nuova), da non
   confondere con i filtri di visualizzazione di filters.py che nascondono
   soltanto.

La colonna 'node_id' contiene la chiave del nodo nel grafo networkx
(es. "ENTE::123") ed è il riferimento usato per la rimozione; 'label' resta
la colonna leggibile per l'utente.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd

from . import metrics as metrics_mod

# Nome riservato della colonna che contiene la chiave del nodo nel grafo.
NODE_ID_COL = "node_id"

# Colonne aggiunte da add_computed_columns (nomi coerenti con metrics.py / report).
COMPUTED_NODE_COLS = ["degree", "degree_pesato", "betweenness", "entropia", "comunita"]


# ---------------------------------------------------------------------------
# Costruzione tabella (nodi ed edge)
# ---------------------------------------------------------------------------

def add_computed_columns(G: nx.Graph, entropy_attribute: str = "category",
                          community_method: str = "louvain") -> nx.Graph:
    """
    Calcola le metriche per-nodo della pipeline e le scrive come attributi
    dei nodi (modifica G in place e lo ritorna, per concatenabilità):
      - degree         : grado non pesato
      - degree_pesato  : grado pesato (weight degli edge)
      - betweenness    : centralità di intermediazione (broker/ponti)
      - entropia       : entropia di vicinato normalizzata (vedi metrics.py)
      - comunita       : id comunità (louvain o fallback greedy_modularity
                         se python-louvain non è installato)
    Essendo attributi veri del grafo, compaiono anche negli export
    (GEXF/GraphML/CSV) e sono usabili da styling/filtri.
    """
    nx.set_node_attributes(G, dict(G.degree()), "degree")
    nx.set_node_attributes(G, dict(G.degree(weight="weight")), "degree_pesato")
    nx.set_node_attributes(G, metrics_mod.betweenness_centrality(G), "betweenness")
    nx.set_node_attributes(G, metrics_mod.neighbor_entropy(G, entropy_attribute), "entropia")
    try:
        partition = metrics_mod.detect_communities(G, method=community_method)
    except ImportError:
        partition = metrics_mod.detect_communities(G, method="greedy_modularity")
    nx.set_node_attributes(G, partition, "comunita")
    return G


def nodes_table(G: nx.Graph, computed: bool = True, entropy_attribute: str = "category",
                 community_method: str = "louvain") -> pd.DataFrame:
    """
    Tabella dei nodi: una riga per nodo, una colonna per ogni attributo
    presente sul grafo (originari da Excel + eventuali attributi già scritti
    da styling/pipeline). Con computed=True calcola e aggiunge prima le
    colonne di COMPUTED_NODE_COLS, così ordinamento e selezione per
    condizione funzionano anche su degree/entropia/comunità.
    """
    if computed:
        add_computed_columns(G, entropy_attribute, community_method)
    rows = []
    for n, attrs in G.nodes(data=True):
        row = {NODE_ID_COL: n}
        row.update(attrs)
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[NODE_ID_COL])
    # ordine colonne leggibile: id, label, poi attributi originari, poi calcolate
    first = [c for c in (NODE_ID_COL, "label") if c in df.columns]
    computed_cols = [c for c in COMPUTED_NODE_COLS if c in df.columns]
    middle = [c for c in df.columns if c not in first + computed_cols]
    return df[first + middle + computed_cols]


def edges_table(G: nx.Graph) -> pd.DataFrame:
    """
    Tabella degli edge: una riga per edge, con source/target (chiavi nodo),
    le rispettive label e una colonna per ogni attributo dell'edge.
    """
    rows = []
    for u, v, attrs in G.edges(data=True):
        row = {
            "source": u,
            "target": v,
            "source_label": G.nodes[u].get("label", u),
            "target_label": G.nodes[v].get("label", v),
        }
        row.update(attrs)
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["source", "target", "source_label", "target_label"])
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Ordinamento e selezione per condizione
# ---------------------------------------------------------------------------

def sort_table(df: pd.DataFrame, by: str, ascending: bool = False) -> pd.DataFrame:
    """Ordina la tabella per una colonna qualsiasi (numerica o categoriale)."""
    if by not in df.columns:
        raise ValueError(f"Colonna '{by}' non presente nella tabella.")
    return df.sort_values(by=by, ascending=ascending, na_position="last").reset_index(drop=True)


# Operatori disponibili per le condizioni: {nome: funzione(serie, valore) -> maschera booleana}
OPERATORS = {
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
    ">": lambda s, v: pd.to_numeric(s, errors="coerce") > float(v),
    ">=": lambda s, v: pd.to_numeric(s, errors="coerce") >= float(v),
    "<": lambda s, v: pd.to_numeric(s, errors="coerce") < float(v),
    "<=": lambda s, v: pd.to_numeric(s, errors="coerce") <= float(v),
    "contiene": lambda s, v: s.astype(str).str.contains(str(v), case=False, na=False),
    "in": lambda s, v: s.isin(list(v) if isinstance(v, (list, tuple, set)) else [v]),
    "è nullo": lambda s, v: s.isna(),
    "non è nullo": lambda s, v: s.notna(),
}


def condition_mask(df: pd.DataFrame, column: str, op: str, value=None) -> pd.Series:
    """
    Maschera booleana per una singola condizione su una colonna della tabella.
    Per == e != prova prima il confronto numerico (così "0" e 0 coincidono),
    poi ripiega sul confronto come stringa.
    """
    if column not in df.columns:
        raise ValueError(f"Colonna '{column}' non presente nella tabella.")
    if op not in OPERATORS:
        raise ValueError(f"Operatore '{op}' non riconosciuto. Disponibili: {list(OPERATORS)}")
    s = df[column]
    if op in ("==", "!="):
        numeric = pd.to_numeric(s, errors="coerce")
        try:
            v_num = float(value)
        except (TypeError, ValueError):
            v_num = None
        if v_num is not None and numeric.notna().any():
            return OPERATORS[op](numeric, v_num)
        return OPERATORS[op](s.astype(str), str(value))
    return OPERATORS[op](s, value)


def select_ids_by_conditions(df: pd.DataFrame, conditions: list[tuple],
                              logic: str = "and", id_col: str = NODE_ID_COL) -> list:
    """
    Valuta una lista di condizioni [(colonna, operatore, valore), ...] sulla
    tabella e restituisce la lista di id (colonna id_col) delle righe che le
    soddisfano. logic='and' (tutte) oppure 'or' (almeno una).
    Esempi:
        select_ids_by_conditions(df, [("degree", "==", 0)])
        select_ids_by_conditions(df, [("category", "==", "Cultura"),
                                       ("degree", "<", 3)], logic="and")
    """
    if df.empty or not conditions:
        return []
    masks = [condition_mask(df, col, op, val) for col, op, val in conditions]
    combined = masks[0]
    for m in masks[1:]:
        combined = (combined | m) if logic == "or" else (combined & m)
    return df.loc[combined, id_col].tolist()


# ---------------------------------------------------------------------------
# Cancellazione nodi (negativo di build_subgraph: rimuovi anziché tieni)
# ---------------------------------------------------------------------------

def remove_nodes(G: nx.Graph, node_ids: list) -> nx.Graph:
    """
    Costruisce un NUOVO grafo senza i nodi indicati e senza gli edge
    incidenti. Il grafo di partenza non viene toccato, coerentemente con lo
    stile della pipeline (le reti derivate sono sempre oggetti nuovi).
    """
    H = G.copy()
    H.remove_nodes_from([n for n in node_ids if n in H])
    return H


def remove_by_conditions(G: nx.Graph, conditions: list[tuple], logic: str = "and",
                          computed: bool = True, entropy_attribute: str = "category",
                          community_method: str = "louvain") -> tuple[nx.Graph, list]:
    """
    Selezione per condizione + rimozione in un passo solo (caso d'uso tipico:
    eliminare tutti i nodi con degree == 0 dopo un filtro o una proiezione).
    Con computed=True le condizioni possono usare anche le colonne calcolate
    (degree, degree_pesato, entropia, comunita).
    Ritorna (nuovo_grafo, lista_id_rimossi).
    """
    df = nodes_table(G, computed=computed, entropy_attribute=entropy_attribute,
                     community_method=community_method)
    to_remove = select_ids_by_conditions(df, conditions, logic=logic)
    return remove_nodes(G, to_remove), to_remove
