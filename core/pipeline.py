"""
pipeline.py
Classe orchestratrice NetworkPipeline: unisce data_io, filters, ego,
projections, metrics, coarsening, temporal, styling, layout, export, report.

Pensata per essere richiamata sia da script/notebook sia da una GUI
(vedi gui/app_streamlit.py), quindi ogni metodo ha side-effect minimi e
ritorna sempre oggetti (grafi/dict) piuttosto che stampare a schermo.

Uso tipico:

    from core.pipeline import NetworkPipeline

    p = NetworkPipeline("nodi.xlsx", "edges.xlsx")
    p.load()
    p.build_bipartite(exclude_default=True)

    ente_ente = p.get_projection("ente", weight_mode="count")
    metrics = p.compute_metrics(ente_ente)
    p.style(ente_ente, color_by="category", size_by="degree_pesato")
    p.export(ente_ente, out_dir="output", basename="ente_ente")
    p.build_report("output/report.html", grafo_principale=ente_ente, metrics=metrics)
"""

from __future__ import annotations

import os

import networkx as nx

from . import data_io, filters, ego, projections, metrics as metrics_mod
from . import coarsening, temporal, styling, layout, export, report
from . import data_table, comparison, animation, robustness, multiplex, persistence, dedup
from . import link_prediction, lifecycle, materiality, impact as impact_mod
from . import simulation as simulation_mod, granular, advanced_metrics, viz3d
from .config import PipelineConfig


class NetworkPipeline:
    def __init__(self, nodes_path: str | None = None, edges_path: str | None = None,
                 config: PipelineConfig | None = None):
        self.nodes_path = nodes_path
        self.edges_path = edges_path
        self.config = config or PipelineConfig()

        self.nodes_df = None
        self.edges_df = None
        self.G_bipartite: nx.Graph | None = None

        # cache delle reti derivate più usate, per comodità nella GUI
        self.graphs: dict[str, nx.Graph] = {}

        # rete multiplex corrente (nx.MultiGraph con attributo layer sugli edge)
        self.M_multiplex: nx.MultiGraph | None = None

    # ------------------------------------------------------------------
    # Caricamento e costruzione
    # ------------------------------------------------------------------

    def load(self):
        self.nodes_df = data_io.load_nodes(self.nodes_path, self.config)
        self.edges_df = data_io.load_edges(self.edges_path, self.config)
        return self

    def build_bipartite(self, exclude_default: bool = True, extra_exclude: list | None = None) -> nx.Graph:
        exclude = list(self.config.excluded_node_labels) if exclude_default else []
        exclude += extra_exclude or []
        self.G_bipartite = data_io.build_bipartite_graph(self.nodes_df, self.edges_df, self.config, exclude)
        self.graphs["bipartite"] = self.G_bipartite
        return self.G_bipartite

    def import_external(self, path: str, fmt: str = "gexf", key: str = "imported") -> nx.Graph:
        """Importa una rete già lavorata in Gephi (gexf/graphml) per riprenderla nella pipeline."""
        if fmt == "gexf":
            G = data_io.import_gexf(path)
        elif fmt == "graphml":
            G = data_io.import_graphml(path)
        else:
            raise ValueError("fmt deve essere 'gexf' o 'graphml'.")
        self.graphs[key] = G
        return G

    def import_generic_tables(self, edges_df, source_col: str, target_col: str,
                               nodes_df=None, id_col: str | None = None,
                               label_col: str | None = None, weight_col: str | None = None,
                               key: str = "imported") -> nx.Graph:
        """Costruisce una rete generica (nessuna assunzione bipartita/di dominio)
        da tabelle nodi/edges con mappatura colonne libera, stile Gephi/Cytoscape
        (vedi data_io.build_graph_from_tables)."""
        G = data_io.build_graph_from_tables(edges_df, source_col, target_col,
                                             nodes_df=nodes_df, id_col=id_col,
                                             label_col=label_col, weight_col=weight_col)
        self.graphs[key] = G
        return G

    # ------------------------------------------------------------------
    # Pulizia nodi (label simili / duplicati / rinomina)
    # ------------------------------------------------------------------

    def find_similar_labels(self, G: nx.Graph, threshold: float = 0.85) -> list[dict]:
        """Gruppi di nodi con label quasi uguali (probabili duplicati da
        nomi sporchi). Da rivedere subito dopo l'import."""
        return dedup.find_similar_labels(G, threshold=threshold)

    def merge_nodes(self, G: nx.Graph, keep, merge_ids: list,
                     new_label: str | None = None) -> nx.Graph:
        """Fonde i nodi duplicati in `keep`: edge riattaccati (pesi sommati),
        attributi ereditati tutti — valori diversi separati da ', '."""
        return dedup.merge_nodes(G, keep, merge_ids, new_label=new_label)

    def rename_node(self, G: nx.Graph, old_id, new_id=None,
                     new_label: str | None = None) -> nx.Graph:
        """Corregge ID e/o label di un nodo (nuovo grafo)."""
        return dedup.rename_node(G, old_id, new_id=new_id, new_label=new_label)

    # ------------------------------------------------------------------
    # Filtri
    # ------------------------------------------------------------------

    def filter_selection(self, G: nx.Graph, criteria: dict, keep_neighbors: bool = False) -> nx.Graph:
        return filters.build_subgraph(G, criteria, keep_neighbors)

    def filter_visualization(self, G: nx.Graph, criteria: dict | None = None,
                              edge_criteria: dict | None = None):
        return filters.visualization_mask(G, criteria, edge_criteria)

    # ------------------------------------------------------------------
    # Ego-network
    # ------------------------------------------------------------------

    def ego_network(self, G: nx.Graph, seed=None, seed_filter: dict | None = None,
                     max_hops: int = 2) -> dict:
        return ego.ego_network_by_degree(G, seed=seed, seed_filter=seed_filter, max_hops=max_hops)

    def ego_on_root(self, max_hops: int = 2) -> dict:
        """Scorciatoia: ego-network con radice = config.root_label, reintroducendo
        quel nodo anche se escluso dalle altre analisi."""
        if not self.config.root_label:
            raise ValueError("Imposta prima il nodo radice (config.root_label).")
        G_full = data_io.build_bipartite_graph(self.nodes_df, self.edges_df, self.config, exclude_labels=[])
        root_nodes = filters.select_nodes(G_full, {"label": self.config.root_label})
        if not root_nodes:
            raise ValueError(f"Nodo radice '{self.config.root_label}' non trovato nel grafo.")
        return ego.ego_network_by_degree(G_full, seed=root_nodes, max_hops=max_hops)

    # ------------------------------------------------------------------
    # Proiezioni
    # ------------------------------------------------------------------

    def get_projection(self, on: str = "ente", weight_mode: str = "count",
                        node_filter: dict | None = None) -> nx.Graph:
        """node_filter (es. {"type": "Fondazione"}): proietta solo i nodi che
        soddisfano il criterio — la "rete delle fondazioni" via progetti condivisi."""
        G = projections.project(self.G_bipartite, on=on, weight_mode=weight_mode,
                                 node_filter=node_filter)
        key = f"projection_{on}" + ("_filtrata" if node_filter else "")
        self.graphs[key] = G
        return G

    def get_projection_by_year(self, on: str = "ente", weight_mode: str = "count",
                                mode: str = "snapshot", node_filter: dict | None = None) -> dict:
        """Proiezione calcolata separatamente per ogni anno del bipartito.
        Ritorna {anno: grafo_proiettato} (mode: 'snapshot' o 'cumulative')."""
        return projections.project_by_year(self.G_bipartite, on=on,
                                            weight_mode=weight_mode, mode=mode,
                                            node_filter=node_filter)

    # ------------------------------------------------------------------
    # Multiplex (layer multipli sugli stessi nodi)
    # ------------------------------------------------------------------

    def build_multiplex(self, G: nx.Graph | None = None, layer_by: str = "anno",
                         expand_records: bool = True) -> nx.MultiGraph:
        """Costruisce il multiplex dividendo gli edge per un attributo
        (es. 'anno' o 'interaction_type') e lo tiene in self.M_multiplex.
        Default: sul grafo bipartito (che porta records/anno/interaction_type)."""
        base = G if G is not None else self.G_bipartite
        if base is None:
            raise ValueError("Serve un grafo: carica i dati o passa G esplicitamente.")
        self.M_multiplex = multiplex.build_multiplex(base, layer_by=layer_by,
                                                      expand_records=expand_records)
        return self.M_multiplex

    def multiplex_add_layer(self, G_layer: nx.Graph, layer_name: str,
                             replace: bool = False) -> nx.MultiGraph:
        """Sovrappone un grafo come nuovo layer del multiplex corrente
        (lo crea se non esiste). Es: la proiezione ente-ente come layer
        sopra la rete totale."""
        self.M_multiplex = multiplex.add_layer(self.M_multiplex, G_layer, layer_name,
                                                replace=replace)
        return self.M_multiplex

    def multiplex_layers(self) -> list[dict]:
        """Riepilogo dei layer del multiplex corrente (nome, nodi, edge)."""
        if self.M_multiplex is None:
            return []
        return multiplex.layer_summary(self.M_multiplex)

    def multiplex_flatten(self, layers: list | None = None, strategy: str = "sum",
                           merge_scope: str = "all", **kwargs):
        """Compone una rete dai layer selezionati risolvendo gli edge paralleli
        (strategy: sum/mean/max/min/count/first/last; merge_scope: all /
        within_layer / none). Vedi multiplex.flatten."""
        if self.M_multiplex is None:
            raise ValueError("Nessun multiplex: chiama prima build_multiplex().")
        G = multiplex.flatten(self.M_multiplex, layers=layers, strategy=strategy,
                               merge_scope=merge_scope, **kwargs)
        self.graphs["multiplex_flat"] = G
        return G

    def multiplex_3d_figure(self, layout_method: str = "spring", **kwargs):
        """Figura 3D interattiva Plotly del multiplex corrente (un piano per
        layer) — vedi viz3d.multiplex_3d_figure."""
        if self.M_multiplex is None:
            raise ValueError("Nessun multiplex: chiama prima build_multiplex().")
        return viz3d.multiplex_3d_figure(self.M_multiplex, layout_method=layout_method, **kwargs)

    # ------------------------------------------------------------------
    # Metriche
    # ------------------------------------------------------------------

    def compute_metrics(self, G: nx.Graph, entropy_attribute: str = "category",
                         community_method: str = "louvain") -> dict:
        return metrics_mod.full_metrics_report(G, entropy_attribute, community_method)

    # ------------------------------------------------------------------
    # Link prediction
    # ------------------------------------------------------------------

    def predict_links(self, G: nx.Graph, method: str = "adamic_adar",
                       top_k: int = 20) -> list[dict]:
        """Coppie non collegate più promettenti (usare sulle proiezioni)."""
        return link_prediction.predict_links(G, method=method, top_k=top_k)

    def link_prediction_holdout(self, test_year, on: str = "ente",
                                 method: str = "adamic_adar", top_k: int = 20) -> dict:
        """Valuta il metodo con hold-out temporale sul bipartito
        (train fino all'anno prima, test sui nuovi legami dell'anno)."""
        if self.G_bipartite is None:
            raise ValueError("Serve il grafo bipartito.")
        return link_prediction.temporal_holdout(self.G_bipartite, test_year,
                                                 on=on, method=method, top_k=top_k)

    def supervised_link_prediction(self, on: str = "ente", top_k: int = 20, **kwargs) -> dict:
        """Link prediction ML: allena sulle transizioni anno→anno e suggerisce
        le coppie più probabili con probabilità (vedi link_prediction_ml)."""
        from . import link_prediction_ml  # import pigro: numpy/sklearn solo se serve
        if self.G_bipartite is None:
            raise ValueError("Serve il grafo bipartito.")
        return link_prediction_ml.supervised_link_prediction(
            self.G_bipartite, on=on, top_k=top_k, **kwargs)

    # ------------------------------------------------------------------
    # Simulazioni
    # ------------------------------------------------------------------

    def granovetter(self, G: nx.Graph, thresholds, seeds: list, **kwargs) -> dict:
        """Cascata di adozione a soglia (vedi simulation.granovetter_cascade)."""
        return simulation_mod.granovetter_cascade(G, thresholds, seeds, **kwargs)

    def ising(self, G: nx.Graph, **kwargs) -> dict:
        """Dinamica di Ising/Glauber: consenso/polarizzazione (vedi simulation)."""
        return simulation_mod.ising_dynamics(G, **kwargs)

    def schelling(self, G: nx.Graph, **kwargs) -> dict:
        """Segregazione alla Schelling su rete (vedi simulation)."""
        return simulation_mod.schelling_segregation(G, **kwargs)

    def simulate_rules(self, rules, **kwargs) -> nx.MultiGraph:
        """Simulazione a classi di nodi con regole (vedi simulation.simulate);
        il risultato è un multiplex analizzabile con i metodi multiplex_*."""
        return simulation_mod.simulate(rules, **kwargs)

    # ------------------------------------------------------------------
    # Impatto (EVPA, stime fornite dall'utente)
    # ------------------------------------------------------------------

    def impact_table(self, rows: list[dict]) -> dict:
        """Tabella di impatto netto EVPA da stime utente (vedi impact.py)."""
        return impact_mod.impact_table(rows)

    # ------------------------------------------------------------------
    # Ciclo di vita del network
    # ------------------------------------------------------------------

    def read_lifecycle(self, metrics_by_year: dict, **kwargs) -> dict:
        """Propone la fase del ciclo di vita (Inception/Growth/Maturity/
        Transition) dagli output di metrics_over_time, con criteri espliciti."""
        return lifecycle.read_lifecycle(metrics_by_year, **kwargs)

    # ------------------------------------------------------------------
    # Metriche multiplex (cross-layer)
    # ------------------------------------------------------------------

    def multiplexity(self) -> dict:
        """Coppie collegate su più layer del multiplex corrente."""
        if self.M_multiplex is None:
            raise ValueError("Nessun multiplex: chiama prima build_multiplex().")
        return multiplex.multiplexity_report(self.M_multiplex)

    def layer_overlap(self) -> list[dict]:
        """Sovrapposizione (Jaccard) tra i layer del multiplex corrente."""
        if self.M_multiplex is None:
            raise ValueError("Nessun multiplex: chiama prima build_multiplex().")
        return multiplex.layer_overlap(self.M_multiplex)

    def intensity_levels(self, levels: list) -> dict:
        """Livello cumulativo massimo di intensità per coppia (brief §1.1),
        con `levels` = layer ordinati dal più debole al più forte."""
        if self.M_multiplex is None:
            raise ValueError("Nessun multiplex: chiama prima build_multiplex().")
        return multiplex.intensity_levels(self.M_multiplex, levels)

    # ------------------------------------------------------------------
    # Matrice di materialità
    # ------------------------------------------------------------------

    def materiality(self, G: nx.Graph, x_attr: str, y_attr: str,
                     size_attr: str | None = None, group_by: str | None = None,
                     agg: str = "mean") -> list[dict]:
        """Tabella X/Y/size/quadrante per la matrice di materialità
        (attributi qualsiasi, anche calcolati)."""
        return materiality.materiality_table(G, x_attr, y_attr, size_attr, group_by, agg)

    def plot_materiality(self, rows: list[dict], path: str, **kwargs) -> str:
        return materiality.plot_materiality(rows, path, **kwargs)

    # ------------------------------------------------------------------
    # Metriche a granularità multiple (densità/entropia per rete, anno,
    # comunità, attributo, filtri a scelta) + export Excel per grafici
    # ------------------------------------------------------------------

    def granular_report(self, G: nx.Graph, scopes: list[str],
                          entropy_attribute: str = "category",
                          community_method: str = "louvain",
                          year_mode: str = "snapshot",
                          custom_filters: list[dict] | None = None,
                          manual_selection: list | None = None):
        """Tabella lunga (una riga per gruppo) con densità, entropie, indice
        E-I, centralizzazione, Gini ecc. per le granularità richieste.
        Le granularità per anno usano il grafo bipartito se disponibile.
        manual_selection: nodi per lo scope 'selezione_manuale' (una 'zona'
        scelta a mano, non una categoria/comunità)."""
        return granular.granular_report(
            G, scopes, entropy_attribute=entropy_attribute,
            community_method=community_method, year_mode=year_mode,
            custom_filters=custom_filters, manual_selection=manual_selection,
            G_temporal=self.G_bipartite if self.G_bipartite is not None else G)

    def export_granular_excel(self, df, path: str, **kwargs) -> str:
        """Excel con foglio dati + pivot per anno + legenda delle metriche."""
        return granular.export_granular_excel(df, path, **kwargs)

    # ------------------------------------------------------------------
    # Metriche avanzate (centralità aggiuntive, k-core, Burt, triadi,
    # omofilia vs modello nullo, specializzazione HHI, concentrazione,
    # distribuzione dei gradi) — vedi core/advanced_metrics.py
    # ------------------------------------------------------------------

    def extra_centralities(self, G: nx.Graph, weight: str | None = "weight"):
        """Eigenvector, pagerank, closeness per nodo (dict separati)."""
        return {
            "eigenvector": advanced_metrics.eigenvector_centrality(G, weight=weight),
            "pagerank": advanced_metrics.pagerank_centrality(G, weight=weight),
            "closeness": advanced_metrics.closeness_centrality(G),
        }

    def centrality_correlation(self, G: nx.Graph, weight: str | None = "weight"):
        return advanced_metrics.centrality_correlation(G, weight=weight)

    def k_core_plateau(self, G: nx.Graph):
        return advanced_metrics.k_core_plateau(G)

    def k_core_subgraph(self, G: nx.Graph, k: int) -> nx.Graph:
        return advanced_metrics.k_core_subgraph(G, k)

    def burt_measures(self, G: nx.Graph, weight: str | None = None):
        return advanced_metrics.burt_measures(G, weight=weight)

    def triad_closure(self, G: nx.Graph):
        return advanced_metrics.triad_closure(G)

    def triad_closure_per_group(self, G: nx.Graph, group_attr: str):
        return advanced_metrics.triad_closure_per_group(G, group_attr=group_attr)

    def mixing_matrix(self, G: nx.Graph, attribute: str):
        return advanced_metrics.mixing_matrix(G, attribute)

    def homophily_vs_null(self, G: nx.Graph, attribute: str, n_reps: int = 200):
        return advanced_metrics.homophily_vs_null(G, attribute, n_reps=n_reps)

    def specialization_per_node(self, G: nx.Graph, attribute: str):
        return advanced_metrics.specialization_per_node(G, attribute)

    def specialization_per_group(self, G: nx.Graph, group_attr: str, target_attr: str):
        return advanced_metrics.specialization_per_group(G, group_attr, target_attr)

    def lorenz_curve(self, values: list):
        return advanced_metrics.lorenz_curve(values)

    def gini(self, values: list) -> float:
        return advanced_metrics.gini(values)

    def degree_distribution_loglog(self, G: nx.Graph, weight: str | None = None):
        return advanced_metrics.degree_distribution_loglog(G, weight=weight)

    # ------------------------------------------------------------------
    # Robustezza / dipendenza (dimensione Health)
    # ------------------------------------------------------------------

    def key_node_dependency(self, G: nx.Graph, top_n: int = 10,
                             strategy: str = "degree") -> list[dict]:
        """Effetto della rimozione dei singoli nodi più centrali (uno alla volta)."""
        return robustness.key_node_dependency(G, top_n=top_n, strategy=strategy)

    def attack_simulation(self, G: nx.Graph, strategy: str = "degree",
                           steps: int = 10, max_fraction: float = 0.5, **kwargs) -> list[dict]:
        """Rimozione progressiva dei nodi più centrali (o casuali) e traiettoria
        della frammentazione della rete."""
        return robustness.attack_simulation(G, strategy=strategy, steps=steps,
                                             max_fraction=max_fraction, **kwargs)

    # ------------------------------------------------------------------
    # Tabella dati (stile "Data Laboratory" di Gephi)
    # ------------------------------------------------------------------

    def nodes_table(self, G: nx.Graph, computed: bool = True,
                     entropy_attribute: str = "category",
                     community_method: str = "louvain"):
        """Tabella dei nodi (DataFrame): attributi originari + colonne calcolate
        (degree, degree_pesato, entropia, comunita) se computed=True."""
        return data_table.nodes_table(G, computed, entropy_attribute, community_method)

    def edges_table(self, G: nx.Graph):
        """Tabella degli edge (DataFrame) con source/target, label e attributi."""
        return data_table.edges_table(G)

    def remove_nodes(self, G: nx.Graph, node_ids: list) -> nx.Graph:
        """Nuovo grafo senza i nodi indicati (e senza gli edge incidenti)."""
        return data_table.remove_nodes(G, node_ids)

    def remove_by_conditions(self, G: nx.Graph, conditions: list[tuple],
                              logic: str = "and", **kwargs) -> tuple[nx.Graph, list]:
        """Rimuove i nodi che soddisfano le condizioni sulle colonne della tabella,
        es. [("degree", "==", 0)]. Ritorna (nuovo_grafo, id_rimossi)."""
        return data_table.remove_by_conditions(G, conditions, logic=logic, **kwargs)

    # ------------------------------------------------------------------
    # Coarse-graining
    # ------------------------------------------------------------------

    def coarse_grain(self, G: nx.Graph, by: str | list[str] = "community",
                      partition: dict | None = None, weight_mode: str = "sum") -> nx.Graph:
        """by: un attributo, 'community', o una lista di questi (chiave
        composita, es. ['bipartite','category']) — vedi coarsening.coarse_grain."""
        by_list = by if isinstance(by, (list, tuple)) else [by]
        if "community" in by_list and partition is None:
            partition = metrics_mod.detect_communities(G)
        return coarsening.coarse_grain(G, by=by, partition=partition, weight_mode=weight_mode)

    # ------------------------------------------------------------------
    # Analisi temporale
    # ------------------------------------------------------------------

    def split_by_year(self, G: nx.Graph, mode: str = "snapshot") -> dict:
        return temporal.split_by_year(G, mode=mode)

    def metrics_over_time(self, G: nx.Graph, mode: str = "snapshot",
                           entropy_attribute: str = "category",
                           community_method: str = "louvain") -> dict:
        return temporal.metrics_over_time(G, mode, entropy_attribute=entropy_attribute,
                                           community_method=community_method)

    def animate(self, path: str, mode: str = "cumulative", on: str | None = None,
                 weight_mode: str = "count", **kwargs) -> str:
        """Salva una GIF dell'evoluzione della rete nel tempo (layout fisso).
        on=None anima il bipartito; on='ente'/'progetto' anima la proiezione
        per anno. kwargs passati ad animation.animate_graphs (fps, color_by,
        show_inactive, frames_dir, ...)."""
        if self.G_bipartite is None:
            raise ValueError("Serve il grafo bipartito: chiama prima build_bipartite().")
        return animation.animate_evolution(self.G_bipartite, path, mode=mode,
                                            on=on, weight_mode=weight_mode, **kwargs)

    def animate_graphs(self, graphs_by_year: dict, path: str, **kwargs) -> str:
        """Anima una qualunque sequenza {anno: grafo} già calcolata."""
        return animation.animate_graphs(graphs_by_year, path, **kwargs)

    # ------------------------------------------------------------------
    # Confronto tra reti/snapshot
    # ------------------------------------------------------------------

    def compare(self, G1: nx.Graph, G2: nx.Graph, labels: tuple = ("prima", "dopo")) -> dict:
        """Confronto generico tra due grafi: nodi/edge entrati-usciti,
        delta di degree per i nodi comuni, delta delle metriche di sintesi."""
        return comparison.compare_graphs(G1, G2, labels=labels)

    def compare_years(self, year1, year2, mode: str = "snapshot") -> dict:
        """Confronta due anni del grafo bipartito (mode: 'snapshot' o 'cumulative')."""
        return comparison.compare_years(self.G_bipartite, year1, year2, mode=mode)

    def comparison_table(self, result: dict, G1: nx.Graph, G2: nx.Graph):
        """La parte per-nodo di un confronto come DataFrame ordinabile."""
        return comparison.delta_table(result, G1, G2)

    # ------------------------------------------------------------------
    # Styling e layout
    # ------------------------------------------------------------------

    def style(self, G: nx.Graph, color_by="category", shade_by=None, size_by=None,
              shape_by="bipartite", size_range=(8, 40), size_log_scale=False,
              shape_target="pyvis", edge_color_by=None, edge_dash_by=None,
              palette_colors=None, shape_map=None) -> nx.Graph:
        """edge_color_by: attributo edge (es. 'layer', 'interaction_type', 'anno')
        per colorare gli edge; edge_dash_by: attributo edge per lo stile di
        linea (solid/dashed/dotted/double); palette_colors: lista di colori hex
        (vedi styling.PALETTES); shape_map: forma scelta per ciascun valore di
        shape_by; letti da tutti i renderer (PNG/HTML/interattivo/GEXF)."""
        return styling.apply_style(G, color_by, shade_by, size_by, shape_by,
                                    size_range, size_log_scale, shape_target,
                                    edge_color_by=edge_color_by, edge_dash_by=edge_dash_by,
                                    palette_colors=palette_colors, shape_map=shape_map)

    def apply_scale(self, G: nx.Graph, node_scale: float = 1.0, edge_scale: float = 1.0,
                     label_scale: float = 1.0) -> nx.Graph:
        """Moltiplicatore complessivo su dimensione nodi/spessore edge/etichette,
        applicato DOPO style() — vedi styling.apply_scale."""
        return styling.apply_scale(G, node_scale=node_scale, edge_scale=edge_scale,
                                    label_scale=label_scale)

    def apply_label_override(self, G: nx.Graph, label_attrs: list | None) -> nx.Graph:
        """Sovrascrive la label mostrata concatenando gli attributi scelti
        (solo sulla copia data, per la resa visiva) — vedi styling.apply_label_override."""
        return styling.apply_label_override(G, label_attrs)

    def scale_layout(self, pos: dict, factor: float) -> dict:
        """'Espansione' (factor>1) / 'Contrazione' (factor<1) di Gephi: riscala
        un layout già calcolato rispetto al suo baricentro (vedi layout.scale_layout)."""
        return layout.scale_layout(pos, factor)

    def compute_layout(self, G: nx.Graph, method: str = "spring", **kwargs) -> dict:
        """method='livelli': passare level_attr (e opzionalmente level_order),
        vedi layout.compute_layout."""
        return layout.compute_layout(G, method=method, **kwargs)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(self, G: nx.Graph, out_dir: str, basename: str, positions: dict | None = None) -> dict:
        return export.export_all(G, out_dir, basename, positions=positions)

    def export_png(self, G: nx.Graph, path: str, **kwargs) -> str:
        return export.export_png(G, path, **kwargs)

    def export_svg(self, G: nx.Graph, path: str, **kwargs) -> str:
        """SVG vettoriale senza sfondo (come l'export SVG di Gephi)."""
        return export.export_svg(G, path, **kwargs)

    def export_excel(self, G: nx.Graph, path: str) -> str:
        """Excel (fogli Nodi+Edges) con le colonne originali; valori multipli
        ereditati da fusioni/accorpamenti separati da ', '."""
        return export.export_excel(G, path)

    def export_html(self, G: nx.Graph, path: str, **kwargs) -> str:
        return export.export_html(G, path, **kwargs)

    def interactive_html(self, G: nx.Graph, **kwargs) -> str:
        """Rete interattiva come stringa HTML (vis.js) per la finestra di
        lavoro della GUI: fisica live (ForceAtlas2/BarnesHut/Repulsion) o
        posizioni precalcolate. Vedi export.build_interactive_html."""
        return export.build_interactive_html(G, **kwargs)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def build_report(self, output_path: str, G: nx.Graph, metrics: dict, titolo: str = "Report Network Analysis",
                      dataset_nome: str = "", network_png_path: str | None = None,
                      coarse_png_path: str | None = None, metrics_by_year: dict | None = None,
                      executive_summary: str | None = None,
                      evolution_gif_path: str | None = None,
                      robustness_rows: list | None = None,
                      dependency_rows: list | None = None,
                      impact_rows: list | None = None) -> str:
        node_labels = {n: G.nodes[n].get("label", n) for n in G.nodes()}
        return report.build_report(
            output_path=output_path, titolo=titolo, dataset_nome=dataset_nome, G=G, metrics=metrics,
            node_labels=node_labels, network_png_path=network_png_path, coarse_png_path=coarse_png_path,
            metrics_by_year=metrics_by_year, executive_summary=executive_summary,
            evolution_gif_path=evolution_gif_path, robustness_rows=robustness_rows,
            dependency_rows=dependency_rows, impact_rows=impact_rows,
        )

    # ------------------------------------------------------------------
    # Persistenza del progetto (lavorare in più riprese)
    # ------------------------------------------------------------------

    def save_project(self, path: str, session: dict | None = None, nome: str = "") -> str:
        """Salva l'intero stato (pipeline + eventuale stato GUI) in un file .nap."""
        return persistence.save_project(path, pipeline=self, session=session, nome=nome)

    @staticmethod
    def load_project(path: str) -> dict:
        """Carica un file .nap: ritorna {"manifest", "pipeline", "session"}.
        Aprire solo file di progetto fidati (payload pickle)."""
        return persistence.load_project(path)
