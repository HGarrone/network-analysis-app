"""
data_io.py
Caricamento dei file Excel (nodi/edges) e costruzione del grafo bipartito
Ente <-> Progetto come networkx.Graph (o DiGraph se serve direzionalità).

Gestisce anche l'import di reti già esportate/modificate in Gephi (GEXF) o
Cytoscape (GraphML / coppia CSV nodi+edges) per riprendere il lavoro fatto
a mano in quei tool.
"""

from __future__ import annotations

import pandas as pd
import networkx as nx

from .config import PipelineConfig, compute_weight


def _split_years(value) -> list[int]:
    """Es. '2024, 2025' -> [2024, 2025]. Gestisce anche valori singoli o NaN."""
    if pd.isna(value):
        return []
    parts = str(value).replace(";", ",").split(",")
    years = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            years.append(int(p))
    return years


def load_nodes(path: str, config: PipelineConfig) -> pd.DataFrame:
    df = pd.read_excel(path)
    c = config.node_cols
    missing = [v for v in c.values() if v not in df.columns]
    if missing:
        raise ValueError(f"Colonne mancanti nel file nodi: {missing}")
    df["_years_list"] = df[c["anno"]].apply(_split_years)
    return df


def load_edges(path: str, config: PipelineConfig) -> pd.DataFrame:
    df = pd.read_excel(path)
    c = config.edge_cols
    missing = [v for v in c.values() if v not in df.columns]
    if missing:
        raise ValueError(f"Colonne mancanti nel file edges: {missing}")

    # Se manca/è nullo il peso pre-calcolato, lo ricalcoliamo dalla formula nota.
    weight_col = c["forza_contributo"]
    needs_recalc = df[weight_col].isna()
    if needs_recalc.any():
        df.loc[needs_recalc, weight_col] = df.loc[needs_recalc].apply(
            lambda r: compute_weight(r[c["interaction_type"]], r[c["importo"]]), axis=1
        )
    # Rete comunque analizzabile anche quando tipo interazione/importo non sono
    # disponibili (es. mappatura colonne libera senza questi campi opzionali):
    # un peso NaN romperebbe dimensionamento/normalizzazione a valle.
    df[weight_col] = df[weight_col].fillna(1.0)
    return df


def build_bipartite_graph(
    nodes_df: pd.DataFrame,
    edges_df: pd.DataFrame,
    config: PipelineConfig,
    exclude_labels: list[str] | None = None,
) -> nx.Graph:
    """
    Costruisce il grafo bipartito Ente <-> Progetto.
    Ogni nodo Ente ha attributi da nodes_df (Type, Category, Ambito/Ruolo, ...).
    Ogni nodo Progetto viene creato a partire dagli attributi presenti negli edges
    (Label Progetto, Category Progetto, ecc.), dato che nodes.xlsx contiene
    prevalentemente enti.
    Ogni edge porta: Anno, Interaction_Type, Importo, weight (Forza contributo).
    """
    nc, ec = config.node_cols, config.edge_cols
    exclude_labels = set(exclude_labels or [])

    G = nx.Graph()

    # --- nodi Ente (da nodes_df) ---
    for _, row in nodes_df.iterrows():
        label = row[nc["label"]]
        if label in exclude_labels:
            continue
        node_id = f"ENTE::{row[nc['id']]}"
        G.add_node(
            node_id,
            bipartite="ente",
            id_originale=row[nc["id"]],
            label=label,
            type=row[nc["type"]],
            category=row[nc["category"]],
            ambito=row[nc["ambito"]],
            sotto_ambito=row[nc["sotto_ambito"]],
            dettaglio=row[nc["dettaglio"]],
            anni=row["_years_list"],
        )

    # --- nodi Progetto + edges (da edges_df) ---
    for _, row in edges_df.iterrows():
        ente_label = row[ec["label_ente"]]
        if ente_label in exclude_labels:
            continue

        ente_id = f"ENTE::{row[ec['source']]}"
        # Se l'ente non era in nodes_df, lo creiamo comunque a partire dagli edges
        if ente_id not in G:
            G.add_node(
                ente_id,
                bipartite="ente",
                id_originale=row[ec["source"]],
                label=ente_label,
                type=row[ec["type_ente"]],
                category=None,
                ambito=None,
                sotto_ambito=None,
                dettaglio=row[ec["dettagli_ente"]],
                anni=[],
            )

        prog_id = f"PROG::{row[ec['target']]}"
        if prog_id not in G:
            G.add_node(
                prog_id,
                bipartite="progetto",
                id_originale=row[ec["target"]],
                label=row[ec["label_progetto"]],
                type="Progetto",
                category=row[ec["category_progetto"]],
                ambito=row[ec["ambito_progetto"]],
                sotto_ambito=row[ec["sotto_ambito_progetto"]],
                dettaglio=row[ec["dettaglio_progetto"]],
                anni=[],
            )

        weight = row[ec["forza_contributo"]]
        anno = row[ec["anno"]]

        if G.has_edge(ente_id, prog_id):
            # multi-relazione ente-progetto nello stesso anno o anni diversi:
            # accumuliamo come lista per non perdere informazione
            G[ente_id][prog_id]["records"].append(
                dict(
                    anno=anno,
                    interaction_type=row[ec["interaction_type"]],
                    importo=row[ec["importo"]],
                    weight=weight,
                )
            )
            G[ente_id][prog_id]["weight"] = max(G[ente_id][prog_id]["weight"], weight)
        else:
            G.add_edge(
                ente_id,
                prog_id,
                weight=weight,
                interaction_type=row[ec["interaction_type"]],
                importo=row[ec["importo"]],
                anno=anno,
                records=[
                    dict(
                        anno=anno,
                        interaction_type=row[ec["interaction_type"]],
                        importo=row[ec["importo"]],
                        weight=weight,
                    )
                ],
            )
        # tiene traccia degli anni di attività anche sul nodo progetto/ente
        if anno not in G.nodes[prog_id]["anni"]:
            G.nodes[prog_id]["anni"].append(anno)
        if anno not in G.nodes[ente_id]["anni"]:
            G.nodes[ente_id]["anni"].append(anno)

    return G


# ---------------------------------------------------------------------------
# Import da Gephi / Cytoscape (per riprendere un lavoro fatto a mano)
# ---------------------------------------------------------------------------

def _normalize_imported_graph(G) -> nx.Graph:
    """
    Il resto della pipeline (community detection, clustering, diametro,
    proiezioni...) è scritto per un nx.Graph semplice non orientato: molti
    algoritmi di networkx (clustering, transitivity, python-louvain) non
    sono implementati per MultiGraph/DiGraph. read_gexf/read_graphml possono
    restituire un multigrafo (se il file ha archi paralleli) o un grafo
    orientato: qui si normalizza sempre a Graph semplice, sommando il peso
    ('weight') degli archi paralleli/direzioni opposte fra la stessa coppia
    di nodi e conservando gli altri attributi del primo arco incontrato.
    """
    if not isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)) and not G.is_directed():
        return G

    H = nx.Graph()
    H.add_nodes_from(G.nodes(data=True))
    for u, v, data in G.edges(data=True):
        if H.has_edge(u, v):
            existing = H.edges[u, v]
            existing["weight"] = existing.get("weight", 1) + data.get("weight", 1)
            existing["n_archi_uniti"] = existing.get("n_archi_uniti", 1) + 1
        else:
            merged = dict(data)
            if "weight" not in merged:
                merged["weight"] = 1
            H.add_edge(u, v, **merged)
    return H


def import_gexf(path: str) -> nx.Graph:
    """Importa un file .gexf esportato da Gephi (preserva posizioni/colori se presenti).
    Se il file contiene un multigrafo o un grafo orientato, viene normalizzato
    a grafo semplice non orientato (archi paralleli uniti, peso sommato)."""
    return _normalize_imported_graph(nx.read_gexf(path))


def import_graphml(path: str) -> nx.Graph:
    """Importa un file .graphml (Cytoscape, Gephi, R/igraph...). Se il file
    contiene un multigrafo o un grafo orientato, viene normalizzato a grafo
    semplice non orientato (archi paralleli uniti, peso sommato)."""
    return _normalize_imported_graph(nx.read_graphml(path))


def _clean_value(v):
    """NaN/NaT di pandas -> None, per coerenza con il resto della pipeline
    (che usa None per 'assente', mai NaN)."""
    return None if pd.isna(v) else v


def build_graph_from_tables(
    edges_df: pd.DataFrame,
    source_col: str,
    target_col: str,
    nodes_df: pd.DataFrame | None = None,
    id_col: str | None = None,
    label_col: str | None = None,
    weight_col: str | None = None,
) -> nx.Graph:
    """
    Costruisce un nx.Graph generico da una tabella edges (obbligatoria) e
    un'eventuale tabella nodi, con mappatura colonne libera — stile import
    Gephi/Cytoscape (ID, Label, Source, Target, Weight...): nessuna
    assunzione bipartita o di dominio, ogni altra colonna (numerica o
    testuale) diventa un attributo del nodo/edge così com'è.
    Nodi presenti solo negli edges (assenti dalla tabella nodi, o se la
    tabella nodi non è fornita) vengono creati al volo con label = id.
    Righe con lo stesso source/target (archi paralleli nella tabella)
    vengono unite sommando il peso (vedi _normalize_imported_graph).
    """
    G = nx.MultiGraph()

    if nodes_df is not None and id_col is not None:
        if id_col not in nodes_df.columns:
            raise ValueError(f"Colonna ID '{id_col}' non trovata nella tabella nodi.")
        for _, row in nodes_df.iterrows():
            node_id = _clean_value(row[id_col])
            if node_id is None:
                continue
            attrs = {k: _clean_value(v) for k, v in row.items() if k != id_col}
            if label_col and label_col in row:
                attrs["label"] = _clean_value(row[label_col])
            attrs.setdefault("label", node_id)
            G.add_node(node_id, **attrs)

    if source_col not in edges_df.columns or target_col not in edges_df.columns:
        raise ValueError(f"Colonne '{source_col}'/'{target_col}' non trovate nella tabella edges.")

    for _, row in edges_df.iterrows():
        u, v = _clean_value(row[source_col]), _clean_value(row[target_col])
        if u is None or v is None:
            continue
        for node_id in (u, v):
            if node_id not in G:
                G.add_node(node_id, label=node_id)

        attrs = {k: _clean_value(val) for k, val in row.items()
                 if k not in (source_col, target_col)}
        if weight_col and weight_col in attrs:
            attrs["weight"] = attrs.pop(weight_col)
        if attrs.get("weight") is None:
            attrs["weight"] = 1
        G.add_edge(u, v, **attrs)

    return _normalize_imported_graph(G)


def import_cytoscape_tables(nodes_csv: str, edges_csv: str,
                             node_id_col: str = "id",
                             edge_source_col: str = "source",
                             edge_target_col: str = "target") -> nx.Graph:
    """Importa una rete esportata da Cytoscape come coppia di tabelle CSV
    (Node Table + Edge Table esportate da File > Export > Table to file)."""
    nodes_df = pd.read_csv(nodes_csv)
    edges_df = pd.read_csv(edges_csv)
    return build_graph_from_tables(edges_df, edge_source_col, edge_target_col,
                                    nodes_df=nodes_df, id_col=node_id_col)
