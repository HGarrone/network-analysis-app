"""
gui_app.py
GUI Streamlit per la pipeline di network analysis.
Avvio: streamlit run gui_app.py

La GUI è un layer sottile sopra core/pipeline.py: ogni bottone/slider chiama
direttamente un metodo di NetworkPipeline, quindi qualunque nuova funzione
aggiunta alla pipeline è facilmente esponibile qui.
"""

import os
import tempfile

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import networkx as nx

from core.pipeline import NetworkPipeline
from core import metrics as metrics_mod
from core import persistence
from core import introspect
from core import styling
from core.config import NODE_COLS, EDGE_COLS

st.set_page_config(page_title="Network Studio", layout="wide")

if "pipeline" not in st.session_state:
    st.session_state.pipeline = None
if "current_graph" not in st.session_state:
    st.session_state.current_graph = None
if "current_graph_name" not in st.session_state:
    st.session_state.current_graph_name = None


def _activate_graph(pipeline_obj, newG, name: str):
    """Rende `newG` la rete attiva E la registra in pipeline.graphs, così
    resta selezionabile in seguito dal menu 'Rete attiva' senza doverla
    ricalcolare né perdere la rete su cui si stava lavorando prima (es. rete
    bipartita + una sua proiezione, entrambe raggiungibili in ogni momento).
    NB: non tocca direttamente st.session_state['active_graph_choice'] (la
    key del selectbox 'Rete attiva'): Streamlit vieta di scrivere la key di
    un widget dopo che è già stato istanziato in questo run, il che succede
    quasi sempre (il selettore è sopra le tab, questa funzione viene quasi
    sempre chiamata da dentro una tab, cioè più sotto nello stesso run).
    Si passa quindi da un marcatore semplice, applicato al PROSSIMO run
    prima che il selectbox venga creato (vedi poco sotto)."""
    pipeline_obj.graphs[name] = newG
    st.session_state.current_graph = newG
    st.session_state.current_graph_name = name
    st.session_state["_pending_active_graph"] = name


def _read_table(uploaded_file):
    """Legge un file caricato (.xlsx o .csv) in un DataFrame."""
    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def _guess_col(columns: list, candidates: list, required: bool = True):
    """Indovina quale colonna corrisponde a un ruolo standard (es. 'source')
    confrontando i nomi senza distinguere maiuscole/minuscole. Se richiesta
    (required=True) e nessun candidato combacia, ripiega sulla prima colonna
    (serve comunque un valore per il selectbox); se opzionale, None."""
    cols_lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return (columns[0] if columns else None) if required else None


# Lati di una rete bipartita: chiavi interne storiche ("ente"/"progetto"),
# mostrate in modo neutro (lato Source / lato Target del file edges).
_SIDE_LABEL = {"ente": "Lato Source (nodi di tipo 1)", "progetto": "Lato Target (nodi di tipo 2)"}

# Ruoli mappabili per il file NODI / EDGES di una rete bipartita,
# con (candidati per l'auto-riconoscimento, obbligatoria?, etichetta mostrata).
# Solo id/source/target sono davvero obbligatori: tutto il resto, se lasciato
# "(nessuna)", viene riempito con None e la pipeline lo gestisce comunque
# (vedi data_io.load_nodes/load_edges).
_BIP_NODE_ROLES = {
    "id":           (["id", "nodeid"], True, "ID nodo"),
    "label":        (["label", "nome", "name"], False, "Etichetta"),
    "type":         (["type", "tipo"], False, "Tipo"),
    "category":     (["category", "categoria"], False, "Categoria (colore/forma)"),
    "ambito":       (["ambito", "ambito/ruolo", "ruolo"], False, "Ambito/Ruolo"),
    "sotto_ambito": (["sotto-ambito", "sotto_ambito"], False, "Sotto-ambito"),
    "dettaglio":    (["dettaglio", "dettagli"], False, "Dettaglio"),
    "anno":         (["anno", "anni", "year", "time", "tempo"], False, "Anno/Tempo"),
}
_BIP_EDGE_ROLES = {
    "source":                 (["source", "from", "id_source", "id ente"], True, "Source (ID nodo 1)"),
    "target":                 (["target", "to", "id_target", "id progetto"], True, "Target (ID nodo 2)"),
    "label_ente":             (["label ente", "nome ente"], False, "Etichetta nodo 1"),
    "type_ente":              (["type ente", "tipo ente"], False, "Tipo nodo 1"),
    "dettagli_ente":          (["dettagli nome ente", "dettagli ente"], False, "Dettagli nodo 1"),
    "interaction_type":       (["interaction_type", "tipo interazione", "tipo_interazione"], False,
                                "Tipo interazione (colore/forma edge)"),
    "label_progetto":         (["label progetto", "nome progetto"], False, "Etichetta nodo 2"),
    "category_progetto":      (["category progetto", "categoria progetto"], False, "Categoria nodo 2 (colore/forma)"),
    "ambito_progetto":        (["ambito progetto"], False, "Ambito nodo 2"),
    "sotto_ambito_progetto":  (["sotto-ambito progetto"], False, "Sotto-ambito nodo 2"),
    "dettaglio_progetto":     (["dettaglio progetto"], False, "Dettaglio nodo 2"),
    "importo":                (["importo", "amount", "value"], False, "Importo"),
    "forza_contributo":       (["forza contributo", "weight", "peso"], False, "Peso / Forza contributo"),
    "anno":                   (["anno", "anni", "year", "time", "tempo"], False, "Anno/Tempo"),
}


def _render_role_mapping(df: pd.DataFrame, roles: dict, key_prefix: str) -> dict:
    """Mostra due colonne di selectbox (una per ruolo canonico) per assegnare
    liberamente le colonne del file caricato. Obbligatorie sempre valorizzate
    (con un guess di default); opzionali hanno anche "(nessuna)". Usa key=
    stabili per widget: restano visibili/modificabili in qualunque rerun
    successivo, così la mappatura si può cambiare in ogni momento senza
    dover ricaricare il file."""
    cols = list(df.columns)
    items = list(roles.items())
    half = (len(items) + 1) // 2
    c1, c2 = st.columns(2)
    mapping = {}
    for i, (role, (candidates, required, label)) in enumerate(items):
        target = c1 if i < half else c2
        with target:
            if required:
                default = _guess_col(cols, candidates, required=True)
                mapping[role] = st.selectbox(f"{label} (obbligatoria)", cols,
                                              index=cols.index(default),
                                              key=f"{key_prefix}_{role}")
            else:
                options = ["(nessuna)"] + cols
                default = _guess_col(cols, candidates, required=False)
                idx = options.index(default) if default else 0
                choice = st.selectbox(f"{label} (opzionale)", options, index=idx,
                                       key=f"{key_prefix}_{role}")
                mapping[role] = None if choice == "(nessuna)" else choice
    return mapping


def _apply_role_mapping(df: pd.DataFrame, mapping: dict, canonical: dict,
                         fallback: dict | None = None) -> pd.DataFrame:
    """Ricostruisce un DataFrame con le colonne rinominate ai nomi canonici
    attesi dalla pipeline (config.NODE_COLS/EDGE_COLS). Ruoli opzionali non
    mappati diventano colonne None (gestite da data_io), salvo un fallback
    esplicito (es. 'label' assente -> usa la colonna scelta per 'id')."""
    fallback = fallback or {}
    out = df.copy()
    for role, canon_name in canonical.items():
        actual_col = mapping.get(role)
        if actual_col and actual_col in df.columns:
            out[canon_name] = df[actual_col]
        elif role in fallback and mapping.get(fallback[role]) in df.columns:
            out[canon_name] = df[mapping[fallback[role]]]
        else:
            out[canon_name] = None
    return out


st.title("🕸️ Network Studio")

# ============================================================
# Sidebar: caricamento dati
# ============================================================
with st.sidebar:
    st.header("1. Dati")
    src = st.radio("Sorgente", ["Carica Excel (nodi + edges)",
                                 "Carica tabelle generiche (stile Gephi)",
                                 "Importa rete esistente (GEXF/GraphML)"])

    if src == "Carica Excel (nodi + edges)":
        st.caption("Carica i due file e assegna le colonne: solo ID nodo e Source/Target "
                   "sono obbligatorie, tutto il resto (etichette, categoria, tipo "
                   "interazione, anno, peso...) è opzionale — se non presente nel tuo "
                   "file lascia '(nessuna)'. Puoi cambiare la mappatura in qualunque "
                   "momento e ricostruire la rete di nuovo con lo stesso bottone.")
        nodes_file = st.file_uploader("File nodi (.xlsx)", type=["xlsx"], key="bip_nodes_file")
        edges_file = st.file_uploader("File edges (.xlsx)", type=["xlsx"], key="bip_edges_file")
        exclude_default = st.checkbox("Escludi nodi di default ('Sostegno non specificato')", value=True)

        node_map, edge_map = None, None
        if nodes_file is not None:
            nodes_df_raw = _read_table(nodes_file)
            st.markdown("**Colonne file nodi**")
            node_map = _render_role_mapping(nodes_df_raw, _BIP_NODE_ROLES, "bip_node")
        if edges_file is not None:
            edges_df_raw = _read_table(edges_file)
            st.markdown("**Colonne file edges**")
            edge_map = _render_role_mapping(edges_df_raw, _BIP_EDGE_ROLES, "bip_edge")

        if node_map and edge_map and st.button("Carica e costruisci rete bipartita"):
            nodes_df = _apply_role_mapping(nodes_df_raw, node_map, NODE_COLS,
                                            fallback={"label": "id"})
            edges_df = _apply_role_mapping(edges_df_raw, edge_map, EDGE_COLS,
                                            fallback={"label_ente": "source",
                                                      "label_progetto": "target"})
            tmp_dir = tempfile.mkdtemp()
            nodes_path = os.path.join(tmp_dir, "nodi.xlsx")
            edges_path = os.path.join(tmp_dir, "edges.xlsx")
            nodes_df.to_excel(nodes_path, index=False)
            edges_df.to_excel(edges_path, index=False)

            pipeline = NetworkPipeline(nodes_path, edges_path)
            pipeline.load()
            G = pipeline.build_bipartite(exclude_default=exclude_default)
            st.session_state.pipeline = pipeline
            _activate_graph(pipeline, G, "bipartite")
            st.success(f"Rete bipartita costruita: {G.number_of_nodes()} nodi, {G.number_of_edges()} edge.")
            # controllo automatico dei nomi 'sporchi' al momento dell'import
            dup = pipeline.find_similar_labels(G, threshold=0.85)
            if dup:
                st.session_state.dup_groups = dup
                st.warning(f"⚠️ Trovati {len(dup)} gruppi di label molto simili che "
                           "potrebbero essere lo stesso nodo: rivedili nella tab "
                           "'🧹 Pulizia nodi' (fusione/rinomina) prima delle analisi.")

    elif src == "Carica tabelle generiche (stile Gephi)":
        st.caption("Qualunque tabella nodi/edges (.xlsx o .csv): scegli quali colonne sono "
                   "ID/Source/Target/Weight, tutte le altre diventano automaticamente "
                   "attributi del nodo/edge — numeriche per gradienti di colore/dimensione, "
                   "testuali per forme/colori/raggruppamenti. Nessuna assunzione bipartita.")
        gen_edges_file = st.file_uploader("File edges (obbligatorio)", type=["xlsx", "csv"],
                                           key="gen_edges_file")
        gen_nodes_file = st.file_uploader("File nodi (opzionale: senza, i nodi si creano "
                                           "dagli edges)", type=["xlsx", "csv"], key="gen_nodes_file")

        if gen_edges_file is not None:
            gen_edges_df = _read_table(gen_edges_file)
            edge_cols = list(gen_edges_df.columns)

            col_g1, col_g2 = st.columns(2)
            with col_g1:
                default_source = _guess_col(edge_cols, ["source", "from", "id_source"])
                gen_source_col = st.selectbox("Colonna Source", edge_cols,
                                               index=edge_cols.index(default_source),
                                               key="gen_source_col")
            with col_g2:
                default_target = _guess_col(edge_cols, ["target", "to", "id_target"])
                gen_target_col = st.selectbox("Colonna Target", edge_cols,
                                               index=edge_cols.index(default_target),
                                               key="gen_target_col")
            weight_options = [None] + edge_cols
            default_weight = _guess_col(edge_cols, ["weight", "peso", "value"], required=False)
            gen_weight_col = st.selectbox(
                "Colonna Weight (opzionale, altrimenti peso = 1 per edge)", weight_options,
                index=weight_options.index(default_weight) if default_weight else 0,
                key="gen_weight_col")

            gen_nodes_df, gen_id_col, gen_label_col = None, None, None
            if gen_nodes_file is not None:
                gen_nodes_df = _read_table(gen_nodes_file)
                node_cols = list(gen_nodes_df.columns)
                col_g3, col_g4 = st.columns(2)
                with col_g3:
                    default_id = _guess_col(node_cols, ["id", "node", "nodeid"])
                    gen_id_col = st.selectbox("Colonna ID (nodi)", node_cols,
                                               index=node_cols.index(default_id),
                                               key="gen_id_col")
                with col_g4:
                    label_options = [None] + node_cols
                    default_label = _guess_col(node_cols, ["label", "name", "nome"], required=False)
                    gen_label_col = st.selectbox("Colonna Label (opzionale)", label_options,
                                                  index=label_options.index(default_label) if default_label else 0,
                                                  key="gen_label_col")

            if st.button("Carica rete generica"):
                pipeline = st.session_state.pipeline or NetworkPipeline()
                G = pipeline.import_generic_tables(
                    gen_edges_df, gen_source_col, gen_target_col,
                    nodes_df=gen_nodes_df, id_col=gen_id_col,
                    label_col=gen_label_col, weight_col=gen_weight_col, key="imported")
                st.session_state.pipeline = pipeline
                _activate_graph(pipeline, G, "imported")
                st.success(f"Rete caricata: {G.number_of_nodes()} nodi, {G.number_of_edges()} edge.")
                dup = pipeline.find_similar_labels(G, threshold=0.85)
                if dup:
                    st.session_state.dup_groups = dup
                    st.warning(f"⚠️ Trovati {len(dup)} gruppi di label molto simili: "
                               "rivedili nella tab '🧹 Pulizia nodi'.")

    else:
        ext_file = st.file_uploader("File rete (.gexf o .graphml)", type=["gexf", "graphml"])
        if ext_file and st.button("Importa rete"):
            tmp_dir = tempfile.mkdtemp()
            ext_path = os.path.join(tmp_dir, ext_file.name)
            with open(ext_path, "wb") as f:
                f.write(ext_file.getbuffer())
            fmt = "gexf" if ext_file.name.endswith(".gexf") else "graphml"
            pipeline = st.session_state.pipeline or NetworkPipeline()
            G = pipeline.import_external(ext_path, fmt=fmt, key="imported")
            st.session_state.pipeline = pipeline
            _activate_graph(pipeline, G, "imported")
            st.success(f"Rete importata: {G.number_of_nodes()} nodi, {G.number_of_edges()} edge.")
            dup = pipeline.find_similar_labels(G, threshold=0.85)
            if dup:
                st.session_state.dup_groups = dup
                st.warning(f"⚠️ Trovati {len(dup)} gruppi di label molto simili: "
                           "rivedili nella tab '🧹 Pulizia nodi'.")

# ============================================================
# Sidebar: salvataggio / ripresa del progetto
# ============================================================
with st.sidebar:
    st.markdown("---")
    st.header("2. Progetto (salva / riprendi)")
    if st.session_state.get("project_loaded_msg"):
        st.success(st.session_state.pop("project_loaded_msg"))

    proj_nome = st.text_input("Nome progetto", value="progetto_network", key="proj_nome")
    if st.session_state.pipeline is not None:
        if st.button("💾 Salva progetto"):
            proj_path = os.path.join(tempfile.mkdtemp(),
                                      f"{proj_nome}{persistence.DEFAULT_EXTENSION}")
            session = persistence.collect_session(st.session_state)
            st.session_state.pipeline.save_project(proj_path, session=session, nome=proj_nome)
            st.session_state.project_file = proj_path
        if st.session_state.get("project_file") and os.path.exists(st.session_state.project_file):
            with open(st.session_state.project_file, "rb") as f:
                st.download_button("Scarica progetto (.nap)", f,
                                    file_name=os.path.basename(st.session_state.project_file))

    proj_up = st.file_uploader("Riprendi un progetto (.nap)", type=["nap", "zip"])
    if proj_up is not None:
        st.caption("⚠️ Aprire solo file di progetto creati da te o da fonti fidate.")
        if st.button("Carica progetto"):
            tmp_path = os.path.join(tempfile.mkdtemp(), proj_up.name)
            with open(tmp_path, "wb") as f:
                f.write(proj_up.getbuffer())
            res = NetworkPipeline.load_project(tmp_path)
            st.session_state.pipeline = res["pipeline"]
            for k, v in res["session"].items():
                try:
                    st.session_state[k] = v
                except Exception:
                    pass  # chiave di un widget già istanziato in questo run: la salta
            man = res["manifest"]
            st.session_state.project_loaded_msg = (
                f"Progetto '{man.get('nome', '')}' caricato (salvato il {man.get('salvato_il', '?')}).")
            st.rerun()

pipeline: NetworkPipeline = st.session_state.pipeline
G = st.session_state.current_graph

if pipeline is None or G is None:
    st.info("Carica i dati dalla barra laterale per iniziare.")
    st.stop()

# ============================================================
# Rete attiva: switch tra tutte le reti calcolate finora (bipartita,
# importata, proiezioni, reti a grana grossa, filtri, ego-network, ...)
# senza doverle ricalcolare né perdere il lavoro fatto sulle altre. Tutte
# le tab qui sotto operano sulla rete scelta qui.
# ============================================================
_graph_names = sorted(pipeline.graphs.keys())
if st.session_state.current_graph_name not in _graph_names:
    _graph_names = [st.session_state.current_graph_name] + _graph_names

# il valore del selectbox va sempre e solo per session_state[key], MAI per
# `index`, insieme: passarli entrambi genera un warning di Streamlit e,
# soprattutto, la key già presente vincerebbe comunque su `index` dal
# secondo run in poi — meglio seminare la key esplicitamente ogni volta che
# serve un valore diverso da quello che l'utente ha scelto a mano.
pending = st.session_state.pop("_pending_active_graph", None)
if pending is not None:
    st.session_state["active_graph_choice"] = pending
elif "active_graph_choice" not in st.session_state:
    st.session_state["active_graph_choice"] = st.session_state.current_graph_name

col_active1, col_active2 = st.columns([3, 1])
with col_active1:
    active_choice = st.selectbox(
        "🕸️ Rete attiva (tutte le tab qui sotto lavorano su questa)",
        _graph_names,
        key="active_graph_choice")
with col_active2:
    st.write("")
    st.write(f"{G.number_of_nodes()} nodi, {G.number_of_edges()} edge")
if active_choice != st.session_state.current_graph_name:
    st.session_state.current_graph = pipeline.graphs[active_choice]
    st.session_state.current_graph_name = active_choice
    st.rerun()

# ============================================================
# Ponte con le altre app locali (GUI Grafici, Pipeline Video): nessun
# accoppiamento di codice, solo file scaricati/ricaricati a mano — vedi
# lo stesso pattern già usato tra Pipeline Video e GUI Grafici semplificata.
# ============================================================
with st.sidebar:
    st.markdown("---")
    with st.expander("🔗 Altre app"):
        # URL dell'app GUI Grafici online: variabile d'ambiente o secrets di Streamlit
        try:
            _grafici_url = os.environ.get("GRAFICI_APP_URL") or st.secrets.get("GRAFICI_APP_URL", "")
        except Exception:
            _grafici_url = ""
        if _grafici_url:
            st.link_button("📊 Apri GUI Grafici (online)", _grafici_url,
                           use_container_width=True,
                           help="Carica lì la tabella nodi/edge scaricata qui sotto per farne un grafico.")

        import json as _json
        _graph_pkg = {
            "name": st.session_state.current_graph_name,
            "n_nodes": G.number_of_nodes(),
            "n_edges": G.number_of_edges(),
            "graph": nx.node_link_data(G),
        }
        st.download_button(
            "📤 Esporta rete per Pipeline Video (.json)",
            _json.dumps(_graph_pkg, ensure_ascii=False, default=str),
            file_name=f"{st.session_state.current_graph_name}_rete.json",
            mime="application/json", use_container_width=True,
            help="Nodi/edge della rete attiva in formato JSON, da caricare in Pipeline Video "
                 "come file dati per un'animazione (per ora manuale: le animazioni automatiche "
                 "specifiche per reti arriveranno in un secondo momento).")

# ============================================================
# Attributi disponibili sulla rete attiva (scoperti dai dati veri, non da
# uno schema fisso): sostituiscono le liste di attributi cucite sul
# dataset originale nei selettori delle tab qui sotto. NODE_GROUP/EDGE_GROUP =
# categoriali + numerici, per i selettori "colora/raggruppa per" dove ha
# senso bucketizzare anche un numero discreto (es. 'anno'); NODE_NUMERIC
# resta separato per gli usi strettamente continui (sfumatura, dimensione).
# ============================================================
_attrs = introspect.graph_attributes(G)
NODE_CATEGORICAL = _attrs["node_categorical"]
NODE_NUMERIC = _attrs["node_numeric"]
NODE_GROUP = NODE_CATEGORICAL + NODE_NUMERIC
EDGE_CATEGORICAL = _attrs["edge_categorical"]
EDGE_NUMERIC = _attrs["edge_numeric"]
EDGE_GROUP = EDGE_CATEGORICAL + EDGE_NUMERIC


def _pick(options: list, preferred: tuple = (), fallback: list | None = None):
    """Lista ordinata (preferiti prima, se presenti) per un selectbox; usa
    `fallback` se `options` è vuota (rete senza attributi utilizzabili)."""
    ordered = introspect.ordered(options, preferred)
    return ordered if ordered else (fallback or [])


# opzioni "virtuali" (non sono attributi reali sul grafo, calcolate al volo
# in _build_view_graph): comunità via Louvain, ed edge che eredita il
# colore del proprio nodo di partenza — così nodi ed edge di una stessa
# comunità combaciano visivamente senza dover unire manualmente due palette.
COMMUNITY_OPTION = "Comunità (Louvain, calcolata al volo)"
EDGE_MATCH_NODE_OPTION = "Come il nodo di partenza (eredita il colore)"


# ============================================================
# Sidebar: 3. Stile e Layout — sempre visibile, nessun bottone "Applica":
# ogni modifica si riflette subito nella vista live in cima alla pagina
# (come un pannello proprietà di Gephi), semplicemente perché l'intero
# script viene rieseguito a ogni interazione e la vista si ridisegna con i
# valori correnti dei widget qui sotto.
# ============================================================
with st.sidebar:
    st.markdown("---")
    st.header("3. Stile e Layout")

    with st.expander("🎨 Colore / forma / dimensione", expanded=True):
        node_attr_options = _pick(NODE_CATEGORICAL, ("type", "category", "ambito", "sotto_ambito", "bipartite"))
        color_by = st.selectbox("Colora nodi per (hue)", [None, COMMUNITY_OPTION] + node_attr_options,
                                 index=2 if node_attr_options else 0, key="style_color_by",
                                 help=f"'{COMMUNITY_OPTION}' calcola le comunità al volo (Louvain), "
                                      "senza doverle generare prima in tab Metriche/Tabella dati.")
        all_palettes = styling.all_palettes()
        # Una palette appena salvata dall'editor qui sotto va selezionata PRIMA che il
        # widget venga creato (Streamlit non permette di cambiarne il valore dopo).
        if "_pending_palette" in st.session_state:
            st.session_state.style_palette = st.session_state.pop("_pending_palette")
        if st.session_state.get("style_palette") not in all_palettes:
            st.session_state.pop("style_palette", None)
        palette_name = st.selectbox("Palette colori", list(all_palettes), key="style_palette",
                                     help="Le palette create da te (🖌️ qui sotto) compaiono in cima.")
        shade_by = st.selectbox("Sfumatura per variabile continua", [None, "degree"] + NODE_NUMERIC,
                                 index=0, key="style_shade_by")
        size_by = st.selectbox("Dimensione nodi per", [None, "degree"] + NODE_NUMERIC,
                                index=0, key="style_size_by")
        shape_by = st.selectbox("Forma nodi per", [None, COMMUNITY_OPTION] + node_attr_options,
                                 index=0, key="style_shape_by")
        shape_map: dict = {}
        if shape_by == COMMUNITY_OPTION:
            st.caption("Con le comunità le forme sono assegnate in automatico "
                       "(le comunità cambiano a ogni ricalcolo).")
        elif shape_by:
            shape_values = sorted({str(G.nodes[n].get(shape_by)) for n in G.nodes()
                                   if G.nodes[n].get(shape_by) is not None})
            if len(shape_values) > 20:
                st.caption(f"{len(shape_values)} valori distinti: forme assegnate in automatico "
                           "(la scelta manuale è disponibile fino a 20 valori).")
            else:
                st.caption("Forma per ciascun valore")
                for i, v in enumerate(shape_values):
                    shape_map[v] = st.selectbox(
                        v, styling.PYVIS_SHAPES, index=i % len(styling.PYVIS_SHAPES),
                        format_func=styling.SHAPE_LABELS.get, key=f"style_shape_{shape_by}_{v}")
        edge_color_by = st.selectbox(
            "Colora EDGE per", [None, EDGE_MATCH_NODE_OPTION] + _pick(EDGE_GROUP, ("layer", "interaction_type", "anno")),
            index=0, key="style_edge_color_by",
            help=f"'{EDGE_MATCH_NODE_OPTION}': l'edge eredita il colore del nodo di partenza — "
                 "comodo per far combaciare i colori di nodi ed edge, es. con la colorazione per comunità.")
        dash_by = st.selectbox("Stile linea EDGE per",
                                [None] + _pick(EDGE_GROUP, ("layer", "interaction_type")),
                                index=0, key="style_dash_by",
                                help="'double' è nativo solo nell'export GEXF (Gephi); su PNG è "
                                     "simulato con due linee, sulla vista interattiva degrada a solid.")

    with st.expander("🖌️ Crea la tua palette colori"):
        st.caption("Parti da una palette esistente, modifica colori e ordine (il 1° colore va "
                   "alla prima categoria, e così via), poi salva: resta disponibile anche "
                   "ai prossimi avvii.")
        if "palette_edit" not in st.session_state:
            st.session_state.palette_edit = list(all_palettes[palette_name])
        base_pick = st.selectbox("Parti da", list(all_palettes), key="palette_edit_base")
        if st.button("⬇️ Carica questa palette", key="palette_edit_load", use_container_width=True):
            st.session_state.palette_edit = list(all_palettes[base_pick])
            st.rerun()

        edit = st.session_state.palette_edit
        for i in range(len(edit)):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            with c1:
                # key con il colore: dopo uno spostamento il picker mostra il colore nuovo
                edit[i] = st.color_picker(f"Colore {i + 1}", value=edit[i],
                                          key=f"palette_edit_c{i}_{edit[i]}")
            with c2:
                if st.button("⬆️", key=f"palette_edit_up{i}", disabled=(i == 0), help="Sposta su"):
                    edit[i - 1], edit[i] = edit[i], edit[i - 1]
                    st.rerun()
            with c3:
                if st.button("⬇️", key=f"palette_edit_dn{i}", disabled=(i == len(edit) - 1),
                             help="Sposta giù"):
                    edit[i + 1], edit[i] = edit[i], edit[i + 1]
                    st.rerun()
            with c4:
                if st.button("🗑️", key=f"palette_edit_del{i}", disabled=(len(edit) <= 2),
                             help="Elimina"):
                    edit.pop(i)
                    st.rerun()
        if st.button("➕ Aggiungi un colore", key="palette_edit_add"):
            edit.append("#888888")
            st.rerun()
        st.markdown("".join(
            f"<span style='display:inline-block;width:22px;height:22px;background:{c};"
            f"margin-right:3px;border:1px solid #999;border-radius:4px'></span>" for c in edit),
            unsafe_allow_html=True)

        new_name = st.text_input("Nome della palette", value="La mia palette", key="palette_edit_name")
        custom = styling.load_custom_palettes()
        s1, s2 = st.columns(2)
        with s1:
            if st.button("💾 Salva", key="palette_edit_save", use_container_width=True):
                name = new_name.strip()
                if not name:
                    st.warning("Dai un nome alla palette.")
                elif name in styling.PALETTES:
                    st.warning("Questo nome è già di una palette predefinita: scegline un altro.")
                else:
                    custom[name] = list(edit)
                    styling.save_custom_palettes(custom)
                    st.session_state._pending_palette = name
                    st.rerun()
        with s2:
            if st.button("🗑️ Elimina", key="palette_edit_remove", use_container_width=True,
                         disabled=new_name.strip() not in custom,
                         help="Elimina la palette personalizzata con questo nome."):
                custom.pop(new_name.strip(), None)
                styling.save_custom_palettes(custom)
                st.rerun()

    with st.expander("🏷️ Etichetta nodi"):
        label_attrs = st.multiselect(
            "Colonna/e da mostrare come etichetta (vuoto = quella caricata dal file)",
            _pick(NODE_GROUP, ()), key="style_label_attrs",
            help="Con più di una colonna, l'etichetta le concatena separate da ' / '. "
                 "Non modifica i dati: solo la resa visiva (PNG/SVG/HTML/GEXF esportati).")
        show_labels_view = st.checkbox("Mostra etichette nella vista", value=True, key="style_show_labels")

    with st.expander("📏 Scala complessiva (per l'immagine)"):
        node_scale = st.slider("Nodi", 0.2, 4.0, 1.0, 0.1, key="style_node_scale")
        edge_scale = st.slider("Edge", 0.2, 4.0, 1.0, 0.1, key="style_edge_scale")
        label_scale = st.slider("Etichette", 0.2, 4.0, 1.0, 0.1, key="style_label_scale")

    with st.expander("🧭 Layout", expanded=True):
        layout_method = st.selectbox("Algoritmo posizioni",
                                      ["spring", "kamada_kawai", "fa2", "livelli"], key="style_layout_method",
                                      help="'fa2' = ForceAtlas2 (nativo networkx). Yifan Hu vero non esiste "
                                           "qui: kamada_kawai è l'alternativa deterministica più vicina — "
                                           "per Yifan Hu autentico esporta il GEXF e apri Gephi.")
        layout_kwargs: dict = {}
        layout_algo_kwargs: dict = {}
        if layout_method == "livelli":
            level_attr = st.selectbox("Attributo che definisce i livelli",
                                       _pick(NODE_GROUP, ("ruolo", "livello", "type")), key="style_level_attr")
            level_values = sorted({str(G.nodes[n].get(level_attr)) for n in G.nodes()
                                    if G.nodes[n].get(level_attr)}) if level_attr else []
            level_order = st.multiselect("Ordine dei livelli (dall'alto in basso; vuoto = alfabetico)",
                                          level_values, key="style_level_order")
            if level_attr:
                layout_kwargs = {"level_attr": level_attr, "level_order": level_order or None}
        elif layout_method == "fa2":
            layout_algo_kwargs["scaling_ratio"] = st.slider("Scaling", 0.5, 10.0, 2.0, 0.5, key="style_fa2_scaling")
            layout_algo_kwargs["gravity"] = st.slider("Gravity", 0.1, 5.0, 1.0, 0.1, key="style_fa2_gravity")
            layout_algo_kwargs["strong_gravity"] = st.checkbox("Stronger gravity", value=False, key="style_fa2_strong")
            layout_algo_kwargs["linlog"] = st.checkbox("LinLog mode", value=False, key="style_fa2_linlog")
            layout_algo_kwargs["max_iter"] = st.slider("Iterazioni", 50, 500, 200, 50, key="style_fa2_iter")
        elif layout_method == "spring":
            layout_algo_kwargs["iterations"] = st.slider("Iterazioni", 20, 300, 100, 10, key="style_spring_iter")

        scale_factor = st.slider("Espandi / contrai (riscala le posizioni già calcolate)",
                                  0.2, 3.0, 1.0, 0.1, key="style_scale_factor")

        physics_solver_map = {"ForceAtlas2": "forceAtlas2Based", "Barnes-Hut": "barnesHut",
                               "Repulsione": "repulsion"}
        physics_solver_choice = st.selectbox("Motore fisica live", list(physics_solver_map),
                                              key="style_physics_solver")
        st.caption("La fisica parte sempre attiva dalle posizioni scelte sopra: per fermarla o "
                   "farla ripartire ESATTAMENTE da dov'è (senza resettarsi alle posizioni "
                   "calcolate) usa la spunta 'Enable physics' nel pannello dentro la vista qui "
                   "sotto, non un controllo da questa barra laterale — quel pannello vive nel "
                   "browser e non causa un ricalcolo, questa barra sì.")


def _build_view_graph(base_G):
    """Applica label/stile/scala correnti (dalla barra laterale) a una copia
    di base_G — usata sia dalla vista live sia dall'export, così sono sempre
    coerenti."""
    Gs = base_G.copy()
    if size_by == "degree" or shade_by == "degree":
        deg = dict(Gs.degree(weight="weight"))
        nx.set_node_attributes(Gs, deg, "degree")
    if color_by == COMMUNITY_OPTION or shape_by == COMMUNITY_OPTION:
        try:
            partition = metrics_mod.detect_communities(Gs, method="louvain")
        except ImportError:
            partition = metrics_mod.detect_communities(Gs, method="greedy_modularity")
        nx.set_node_attributes(Gs, {n: f"Comunita_{c}" for n, c in partition.items()}, "community")

    styling.apply_label_override(Gs, label_attrs)
    real_color_by = "community" if color_by == COMMUNITY_OPTION else color_by
    real_shape_by = "community" if shape_by == COMMUNITY_OPTION else shape_by
    real_edge_color_by = None if edge_color_by == EDGE_MATCH_NODE_OPTION else edge_color_by
    pipeline.style(Gs, color_by=real_color_by, shade_by=shade_by, size_by=size_by,
                    shape_by=real_shape_by, edge_color_by=real_edge_color_by, edge_dash_by=dash_by,
                    palette_colors=all_palettes[palette_name], shape_map=shape_map)
    if edge_color_by == EDGE_MATCH_NODE_OPTION:
        for u, v, d in Gs.edges(data=True):
            d["viz_edge_color"] = Gs.nodes[u].get("viz_color", "#888888")
    pipeline.apply_scale(Gs, node_scale=node_scale, edge_scale=edge_scale, label_scale=label_scale)
    return Gs


def _compute_view_positions(Gs):
    """Layout corrente (algoritmo + parametri + espandi/contrai dalla barra
    laterale), in cache per rete/parametri identici (vedi layout.py)."""
    if layout_method == "livelli" and not layout_kwargs:
        return None
    pos = pipeline.compute_layout(Gs, method=layout_method, **layout_kwargs, **layout_algo_kwargs)
    if scale_factor != 1.0:
        pos = pipeline.scale_layout(pos, scale_factor)
    return pos


# ============================================================
# Vista live: sempre in cima alla pagina, sopra tutte le tab, si aggiorna
# da sola a ogni modifica di stile/layout o di rete attiva (nessun bottone
# "Applica" — vedi _build_view_graph/_compute_view_positions sopra).
# ============================================================
st.markdown("---")
if G.number_of_nodes() > 1500:
    st.warning(f"La rete ha {G.number_of_nodes()} nodi: la fisica live può essere lenta. "
               "Disattivala dal pannello 'Enable physics' dentro la vista qui sotto, o filtra "
               "prima la rete.")

_Gview = _build_view_graph(G)
_pos_view = _compute_view_positions(_Gview)
if _pos_view is None:
    st.info("Scegli un attributo per i livelli in barra laterale (sezione Layout) per vedere la rete.")
else:
    _html_view = pipeline.interactive_html(
        _Gview, physics=True, solver=physics_solver_map[physics_solver_choice],
        positions=_pos_view, show_labels=show_labels_view, show_config_panel=True)
    # st.iframe sostituisce components.html (deprecato, verrà rimosso da Streamlit)
    if hasattr(st, "iframe"):
        st.iframe(_html_view, height=650)
    else:
        components.html(_html_view, height=650, scrolling=True)
    st.session_state.view_html = _html_view
    st.session_state.view_graph = _Gview
    st.session_state.view_positions = _pos_view

# ============================================================
# Tabs principali
# ============================================================
# Tabella dati per prima: la prima cosa utile dopo il caricamento, insieme
# alla vista live qui sopra, è controllare nodi/edge a colpo d'occhio prima
# di derivare proiezioni o calcolare metriche.
# NB: l'ordine delle tab mostrate è SOLO quello di questa lista — i blocchi
# `with tab_x:` più sotto possono restare nel loro ordine attuale nel file.
(tab_table, tab_derive, tab_multiplex, tab_clean, tab_filter, tab_metrics,
 tab_temporal, tab_predict, tab_sim, tab_export) = st.tabs(
    ["📋 Tabella dati", "🔀 Reti derivate", "🧅 Multiplex",
     "🧹 Pulizia nodi", "🔍 Filtri / Ego-network", "📊 Metriche", "📅 Analisi temporale",
     "🔮 Link prediction", "🧪 Simulazione", "💾 Export & Report"]
)

# ------------------------------------------------------------------
# Reti derivate: proiezioni e coarse-graining
# ------------------------------------------------------------------
with tab_derive:
    st.subheader("Rete attualmente attiva")
    st.write(f"**{st.session_state.current_graph_name}** — {G.number_of_nodes()} nodi, {G.number_of_edges()} edge")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Proiezione bipartita**")
        proj_side = st.selectbox("Lato da proiettare", ["ente", "progetto"], format_func=_SIDE_LABEL.get)
        proj_weight = st.selectbox("Modalità peso", ["count", "sum_weight", "jaccard"])

        st.caption("Filtro opzionale sui nodi proiettati (es. type = X → rete dei soli "
                   "nodi di tipo X, collegati dai nodi dell'altro lato che hanno in comune).")
        base_b = pipeline.G_bipartite if pipeline.G_bipartite is not None else G
        base_b_categorical = introspect.graph_attributes(base_b)["node_categorical"]
        proj_filt_options = [None] + _pick(base_b_categorical, ("type", "category", "ambito"))
        proj_filt_attr = st.selectbox("Filtra nodi proiettati per", proj_filt_options,
                                       key="proj_filt_attr")
        proj_node_filter = None
        if proj_filt_attr:
            proj_filt_values = st.multiselect(
                "Valori", sorted({str(base_b.nodes[n].get(proj_filt_attr))
                                  for n in base_b.nodes()
                                  if base_b.nodes[n].get(proj_filt_attr)
                                  and base_b.nodes[n].get("bipartite") == proj_side}),
                key="proj_filt_values")
            if proj_filt_values:
                proj_node_filter = {proj_filt_attr: proj_filt_values}

        if pipeline.G_bipartite is None:
            st.caption("Serve la rete bipartita (carica i file Excel dalla barra laterale).")
        elif st.button("Calcola proiezione"):
            newG = pipeline.get_projection(proj_side, weight_mode=proj_weight,
                                            node_filter=proj_node_filter)
            name = f"projection_{proj_side}" + ("_filtrata" if proj_node_filter else "")
            _activate_graph(pipeline, newG, name)
            st.rerun()

    with col2:
        st.markdown("**Coarse-graining (fusione nodi)**")
        st.caption("Opera sulla rete attiva scelta sopra (non serve la rete bipartita). Scegli "
                   "più di un attributo per una chiave composita (es. 'bipartite' + 'category' → "
                   "tiene distinte le categorie dei due lati di un bipartito invece di fonderle).")
        by_options = ["community"] + _pick(NODE_CATEGORICAL, ("type", "category"))
        coarse_by = st.multiselect("Accorpa per", by_options,
                                    default=by_options[:1] if by_options else [])
        if coarse_by and st.button("Genera rete a grana grossa"):
            coarseG = pipeline.coarse_grain(G, by=coarse_by)
            name = f"coarse_{'_'.join(coarse_by)}_di_{st.session_state.current_graph_name}"
            _activate_graph(pipeline, coarseG, name)
            st.rerun()

    if pipeline.G_bipartite is not None and st.session_state.current_graph_name != "bipartite":
        st.markdown("---")
        if st.button("↩️ Passa alla rete bipartita originale"):
            _activate_graph(pipeline, pipeline.G_bipartite, "bipartite")
            st.rerun()

# ------------------------------------------------------------------
# Multiplex (layer multipli sugli stessi nodi)
# ------------------------------------------------------------------
with tab_multiplex:
    st.subheader("Rete multiplex: layer multipli sugli stessi nodi")
    st.caption("Ogni edge vive su un layer (es. un anno, o un tipo di relazione). "
               "Puoi sovrapporre layer a scelta "
               "e comporre una rete risolvendo gli edge paralleli con le strategie di Gephi.")

    # --- 1. costruzione dal bipartito ---
    st.markdown("**1. Crea il multiplex dalla rete bipartita** (un layer per valore dell'attributo)")
    _bip_edge_group = (introspect.graph_attributes(pipeline.G_bipartite)["edge_categorical"]
                        + introspect.graph_attributes(pipeline.G_bipartite)["edge_numeric"]
                        if pipeline.G_bipartite is not None else [])
    mux_by = st.selectbox("Attributo che definisce i layer",
                           _pick(_bip_edge_group, ("interaction_type", "anno")),
                           key="mux_by",
                           help="Le multi-relazioni accorpate (records) vengono espanse: "
                                "ogni relazione finisce nel proprio layer.")
    if st.button("Crea multiplex"):
        if pipeline.G_bipartite is None:
            st.error("Serve il grafo bipartito: carica i file Excel dalla barra laterale.")
        else:
            M = pipeline.build_multiplex(layer_by=mux_by)
            st.success(f"Multiplex creato: {M.number_of_nodes()} nodi, "
                       f"{M.number_of_edges()} edge su {len(pipeline.multiplex_layers())} layer.")

    # --- 2. aggiunta della rete corrente come layer ---
    st.markdown("---")
    st.markdown("**2. Aggiungi la rete corrente come layer** (es. una proiezione "
                "sopra la rete totale)")
    mux_layer_name = st.text_input("Nome del nuovo layer",
                                    value=st.session_state.current_graph_name or "layer",
                                    key="mux_layer_name")
    mux_replace = st.checkbox("Sostituisci se il layer esiste già", value=False)
    if st.button("Aggiungi come layer"):
        if isinstance(G, nx.MultiGraph):
            st.error("La rete corrente è già un multigrafo: componi prima una rete semplice.")
        else:
            try:
                pipeline.multiplex_add_layer(G, mux_layer_name, replace=mux_replace)
                st.success(f"Layer '{mux_layer_name}' aggiunto.")
            except ValueError as e:
                st.error(str(e))

    # --- 3. riepilogo e composizione ---
    st.markdown("---")
    st.markdown("**3. Seleziona i layer e componi la rete**")
    layers_info = pipeline.multiplex_layers()
    if not layers_info:
        st.info("Nessun multiplex ancora: crealo dal bipartito (1) o aggiungi layer (2).")
    else:
        st.dataframe(pd.DataFrame(layers_info))
        mux_sel = st.multiselect("Layer da sovrapporre", [r["layer"] for r in layers_info],
                                  default=[r["layer"] for r in layers_info], key="mux_sel")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            strategy_labels = {"Somma": "sum", "Media": "mean", "Massimo": "max",
                                "Minimo": "min", "Conteggio": "count",
                                "Primo": "first", "Ultimo": "last"}
            mux_strategy = st.selectbox("Strategia di unione dei pesi (stile Gephi)",
                                         list(strategy_labels), key="mux_strategy")
        with col_m2:
            scope_labels = {"Unisci tutto (un edge per coppia)": "all",
                             "Non unire tra layer diversi (un edge per layer)": "within_layer",
                             "Non unire mai (mantieni tutti gli edge paralleli)": "none"}
            mux_scope = st.selectbox("Risoluzione degli edge paralleli", list(scope_labels),
                                      key="mux_scope")
        mux_isolated = st.checkbox("Includi i nodi dei layer selezionati rimasti isolati", value=False)

        if scope_labels[mux_scope] != "all":
            st.warning("Con edge paralleli (multigrafo) alcune analisi — louvain, proiezioni — "
                       "non sono disponibili: usa 'Unisci tutto' per la rete da analizzare.")

        if st.button("Componi rete dai layer selezionati") and mux_sel:
            newG = pipeline.multiplex_flatten(layers=mux_sel,
                                               strategy=strategy_labels[mux_strategy],
                                               merge_scope=scope_labels[mux_scope],
                                               include_isolated=mux_isolated)
            name = "multiplex_" + "_".join(map(str, mux_sel))[:40]
            _activate_graph(pipeline, newG, name)
            st.rerun()

        # --- metriche multiplex (cross-layer) ---
        st.markdown("---")
        with st.expander("📊 Metriche multiplex (coppie su più layer, sovrapposizione, livelli)"):
            if st.button("Calcola metriche multiplex"):
                st.session_state.mux_report = pipeline.multiplexity()
                st.session_state.mux_overlap = pipeline.layer_overlap()
            if st.session_state.get("mux_report"):
                r = st.session_state.mux_report
                c1, c2, c3 = st.columns(3)
                c1.metric("Coppie collegate", r["n_coppie"])
                c2.metric("Coppie multiplex (≥2 layer)", r["n_coppie_multiplex"])
                c3.metric("Frazione multiplex", r["frazione_multiplex"])
                if r["coppie_multiplex"]:
                    st.markdown("**Coppie collegate su più layer**")
                    st.dataframe(pd.DataFrame(r["coppie_multiplex"])[
                        ["label_u", "label_v", "n_layer", "layers"]], width="stretch", height=250)
                if st.session_state.get("mux_overlap"):
                    st.markdown("**Sovrapposizione tra layer (Jaccard sulle coppie)**")
                    st.dataframe(pd.DataFrame(st.session_state.mux_overlap), width="stretch")

            st.markdown("**Livelli cumulativi di intensità** — ordina i layer dal più "
                        "debole al più forte (es. contatto → collaborazione → partnership)")
            liv_order = st.multiselect("Ordine dei livelli", [r["layer"] for r in layers_info],
                                        key="liv_order")
            if st.button("Calcola livelli di intensità") and liv_order:
                st.session_state.mux_levels = pipeline.intensity_levels(liv_order)
            if st.session_state.get("mux_levels"):
                lv = st.session_state.mux_levels
                st.dataframe(pd.DataFrame([
                    {"Livello massimo": k, "N. coppie": v}
                    for k, v in lv["conteggio_per_livello"].items()]), width="stretch")
                if lv["per_coppia"]:
                    st.dataframe(pd.DataFrame(lv["per_coppia"])[
                        ["label_u", "label_v", "livello_massimo", "livelli_presenti"]],
                        width="stretch", height=250)

        # --- vista 3D interattiva (un piano per layer) ---
        st.markdown("---")
        with st.expander("🧊 Vista 3D interattiva (un piano per layer)"):
            st.caption("Ogni layer su un piano orizzontale impilato sull'asse z, stesse "
                       "coordinate (x, y) per un nodo su tutti i layer, linee tratteggiate a "
                       "collegare le occorrenze dello stesso nodo tra layer diversi. "
                       "Ruotabile/zoommabile col mouse.")
            col_3d1, col_3d2, col_3d3 = st.columns(3)
            with col_3d1:
                viz3d_layout = st.selectbox("Layout (x, y)", ["spring", "kamada_kawai", "fa2"],
                                             key="viz3d_layout")
            with col_3d2:
                viz3d_spacing = st.slider("Distanza tra i piani", 0.3, 3.0, 1.0, 0.1,
                                           key="viz3d_spacing")
            with col_3d3:
                viz3d_labels = st.checkbox("Etichette nodi", value=False, key="viz3d_labels")
            viz3d_links = st.checkbox("Collega lo stesso nodo tra layer (linee tratteggiate)",
                                       value=True, key="viz3d_links")
            if st.button("Genera vista 3D"):
                try:
                    st.session_state.viz3d_fig = pipeline.multiplex_3d_figure(
                        layout_method=viz3d_layout, layer_spacing=viz3d_spacing,
                        show_labels=viz3d_labels, show_interlayer_links=viz3d_links)
                except ValueError as e:
                    st.error(str(e))
            if st.session_state.get("viz3d_fig") is not None:
                st.plotly_chart(st.session_state.viz3d_fig, width="stretch")

# ------------------------------------------------------------------
# Pulizia nodi: label simili, fusione duplicati, rinomina
# ------------------------------------------------------------------
with tab_clean:
    st.subheader("Label simili (probabili duplicati)")
    st.caption("Nomi 'sporchi' dello stesso nodo scritto in modi diversi vengono proposti come "
               "gruppi da unire. Meglio pulire la RETE BIPARTITA subito dopo l'import, prima di "
               "proiezioni e analisi: le reti derivate ereditano la pulizia. Nella fusione gli "
               "attributi diversi vengono ereditati tutti, separati da ', '.")

    sim_threshold = st.slider("Soglia di somiglianza", 0.70, 0.99, 0.85, 0.01,
                               help="1 = identici dopo normalizzazione (maiuscole/accenti/punteggiatura); "
                                    "abbassa per trovare più candidati (con più falsi positivi).")
    if st.button("🔎 Trova label simili nella rete attiva"):
        st.session_state.dup_groups = pipeline.find_similar_labels(G, threshold=sim_threshold)

    groups = st.session_state.get("dup_groups")
    if groups is not None:
        if not groups:
            st.success("Nessun gruppo di label simili sopra la soglia.")
        else:
            st.dataframe(pd.DataFrame([
                {"Gruppo": i, "Similarità min": g["similarita_min"],
                 "Label": " | ".join(lab for _, lab in g["nodi"]),
                 "N. nodi": len(g["nodi"])}
                for i, g in enumerate(groups)]), width="stretch")

            st.markdown("**Unisci i nodi di un gruppo**")
            grp_idx = st.selectbox("Gruppo", list(range(len(groups))),
                                    format_func=lambda i: f"{i}: " + " | ".join(
                                        lab for _, lab in groups[i]["nodi"])[:80],
                                    key="dup_grp_idx")
            membri = groups[grp_idx]["nodi"]
            keep_label = st.selectbox("Nodo da MANTENERE", [lab for _, lab in membri],
                                       key="dup_keep")
            keep_id = [nid for nid, lab in membri if lab == keep_label][0]
            da_unire = st.multiselect("Nodi da unire nel mantenuto",
                                       [lab for _, lab in membri if lab != keep_label],
                                       default=[lab for _, lab in membri if lab != keep_label],
                                       key="dup_merge")
            merge_ids = [nid for nid, lab in membri if lab in da_unire]
            nuovo_nome = st.text_input("Label finale (opzionale, vuoto = tieni quella del mantenuto)",
                                        key="dup_newlabel")
            if st.button("🔗 Unisci i nodi selezionati") and merge_ids:
                was_bipartite = st.session_state.current_graph_name.startswith("bipartite")
                newG = pipeline.merge_nodes(G, keep_id, merge_ids,
                                             new_label=nuovo_nome or None)
                _activate_graph(pipeline, newG, f"{st.session_state.current_graph_name}_puliti")
                if was_bipartite:
                    pipeline.G_bipartite = newG  # le proiezioni successive usano la rete pulita
                    pipeline.graphs["bipartite"] = newG
                st.session_state.dup_groups = None
                st.session_state.nodes_table_df = None
                st.success(f"Uniti {len(merge_ids)} nodi. Nuova rete: "
                           f"{newG.number_of_nodes()} nodi, {newG.number_of_edges()} edge.")
                st.rerun()

    st.markdown("---")
    st.subheader("Rinomina / correggi un nodo (ID e label)")
    node_labels_all = {n: str(G.nodes[n].get("label", n)) for n in G.nodes()}
    ren_label = st.selectbox("Nodo", sorted(node_labels_all.values()), key="ren_sel")
    ren_id = [n for n, lab in node_labels_all.items() if lab == ren_label][0]
    st.caption(f"ID attuale: `{ren_id}`")
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        ren_new_id = st.text_input("Nuovo ID (vuoto = invariato)", key="ren_new_id")
    with col_r2:
        ren_new_label = st.text_input("Nuova label (vuota = invariata)", key="ren_new_label")
    if st.button("✏️ Applica rinomina") and (ren_new_id or ren_new_label):
        try:
            newG = pipeline.rename_node(G, ren_id, new_id=ren_new_id or None,
                                         new_label=ren_new_label or None)
            _activate_graph(pipeline, newG, st.session_state.current_graph_name)
            if st.session_state.current_graph_name.startswith("bipartite"):
                pipeline.G_bipartite = newG
                pipeline.graphs["bipartite"] = newG
            st.session_state.nodes_table_df = None
            st.success("Nodo rinominato.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

# ------------------------------------------------------------------
# Filtri e ego-network
# ------------------------------------------------------------------
with tab_filter:
    st.subheader("Filtro di selezione (costruisce una nuova sotto-rete)")
    attr_options = _pick(NODE_CATEGORICAL, ("type", "category", "ambito", "sotto_ambito"))
    filt_attr = st.selectbox("Attributo", attr_options, key="filt_attr")
    values_available = sorted({str(G.nodes[n].get(filt_attr)) for n in G.nodes() if G.nodes[n].get(filt_attr)})
    filt_values = st.multiselect("Valori", values_available, key="filt_values")
    keep_neighbors = st.checkbox("Includi vicini diretti dei nodi filtrati", value=True)

    if st.button("Applica filtro di selezione") and filt_values:
        sub = pipeline.filter_selection(G, {filt_attr: filt_values}, keep_neighbors=keep_neighbors)
        _activate_graph(pipeline, sub, f"filtro_{filt_attr}_di_{st.session_state.current_graph_name}")
        st.rerun()

    st.markdown("---")
    st.subheader("Ego-network generalizzata")
    ego_mode = st.radio("Seme", ["Nodo singolo", "Filtro per attributo"])
    max_hops = st.slider("Gradi di distanza (hop)", 1, 4, 2)

    if ego_mode == "Nodo singolo":
        node_labels = {n: G.nodes[n].get("label", n) for n in G.nodes()}
        seed_label = st.selectbox("Nodo seme", sorted(node_labels.values()))
        seed_id = [n for n, lab in node_labels.items() if lab == seed_label][0]
        if st.button("Calcola ego-network"):
            st.session_state.ego_results = pipeline.ego_network(G, seed=seed_id, max_hops=max_hops)
            st.session_state.ego_basename = f"ego_{seed_label}"
    else:
        ego_attr = st.selectbox("Attributo filtro seme", attr_options, key="ego_attr")
        ego_values_available = sorted({str(G.nodes[n].get(ego_attr)) for n in G.nodes() if G.nodes[n].get(ego_attr)})
        ego_values = st.multiselect("Valori seme", ego_values_available, key="ego_values")
        if st.button("Calcola ego-network da filtro") and ego_values:
            st.session_state.ego_results = pipeline.ego_network(
                G, seed_filter={ego_attr: ego_values}, max_hops=max_hops)
            st.session_state.ego_basename = f"ego_filtro_{ego_attr}"

    # --- scelta del grado di vicinanza da attivare ---
    if st.session_state.get("ego_results"):
        st.markdown("---")
        st.markdown(f"**Risultati per grado di vicinanza** ({st.session_state.ego_basename})")
        res = st.session_state.ego_results
        st.dataframe(pd.DataFrame([
            {"Grado (hop)": r, "Nodi interni": len(v["internal_nodes"]),
             "Nodi esterni": len(v["external_nodes"]),
             "Edge": v["subgraph"].number_of_edges()}
            for r, v in sorted(res.items())]))
        hop_sel = st.selectbox("Grado di vicinanza da attivare", sorted(res.keys()),
                                key="ego_hop_sel")
        if st.button("Attiva la sotto-rete al grado selezionato", key="ego_activate"):
            _activate_graph(pipeline, res[hop_sel]["subgraph"],
                             f"{st.session_state.ego_basename}_hop{hop_sel}")
            st.session_state.ego_results = None
            st.rerun()

# ------------------------------------------------------------------
# Tabella dati (stile "Data Laboratory" di Gephi)
# ------------------------------------------------------------------
with tab_table:
    st.subheader("Tabella nodi della rete attiva")
    st.caption("Una riga per nodo, una colonna per attributo — incluse le colonne calcolate "
               "(degree, degree_pesato, entropia, comunita). Ordina, seleziona per condizione "
               "ed elimina i nodi selezionati dal grafo attivo (rimozione vera, non solo visiva).")

    # id della rete attiva: se cambia, la tabella in memoria è obsoleta
    graph_id = f"{st.session_state.current_graph_name}|{G.number_of_nodes()}|{G.number_of_edges()}"

    col_a, col_b = st.columns(2)
    with col_a:
        table_entropy_attr = st.selectbox("Attributo per l'entropia",
                                           _pick(NODE_GROUP, ("category", "type", "ambito")),
                                           key="table_entropy_attr")
    with col_b:
        table_comm_method = st.selectbox("Metodo comunità", ["louvain", "greedy_modularity", "label_propagation"],
                                          key="table_comm_method")

    if st.button("Genera / aggiorna tabella nodi"):
        st.session_state.nodes_table_df = pipeline.nodes_table(
            G, computed=True, entropy_attribute=table_entropy_attr,
            community_method=table_comm_method)
        st.session_state.nodes_table_graph_id = graph_id
        st.session_state.table_conditions = []

    if st.session_state.get("nodes_table_df") is not None:
        if st.session_state.get("nodes_table_graph_id") != graph_id:
            st.warning("La rete attiva è cambiata dopo l'ultima generazione: rigenera la tabella.")
        else:
            from core import data_table as dt

            df = st.session_state.nodes_table_df
            sortable_cols = [c for c in df.columns if c != dt.NODE_ID_COL]

            # --- ordinamento ---
            col_s1, col_s2 = st.columns([3, 1])
            with col_s1:
                sort_col = st.selectbox("Ordina per colonna", sortable_cols,
                                         index=sortable_cols.index("degree") if "degree" in sortable_cols else 0)
            with col_s2:
                sort_asc = st.checkbox("Crescente", value=False)
            df_view = dt.sort_table(df, by=sort_col, ascending=sort_asc)
            st.dataframe(df_view, width="stretch", height=400)
            st.caption(f"{len(df_view)} nodi. Le colonne sono ordinabili anche cliccando sull'intestazione.")
            st.download_button("📤 Esporta tabella nodi per GUI Grafici (.csv)",
                               df_view.to_csv(index=False).encode("utf-8"),
                               file_name="nodi_rete.csv", mime="text/csv",
                               key="export_nodes_csv_guigrafici")

            # --- selezione per condizione ---
            st.markdown("---")
            st.markdown("**Selezione per condizione** (es. degree == 0, category == Cultura)")
            if "table_conditions" not in st.session_state:
                st.session_state.table_conditions = []

            col_c1, col_c2, col_c3, col_c4 = st.columns([2, 1, 2, 1])
            with col_c1:
                cond_col = st.selectbox("Colonna", sortable_cols, key="cond_col")
            with col_c2:
                cond_op = st.selectbox("Operatore", list(dt.OPERATORS.keys()), key="cond_op")
            with col_c3:
                cond_val = st.text_input("Valore (per 'in': valori separati da virgola)", key="cond_val",
                                          disabled=cond_op in ("è nullo", "non è nullo"))
            with col_c4:
                st.write("")
                if st.button("➕ Aggiungi"):
                    value = ([v.strip() for v in cond_val.split(",")] if cond_op == "in"
                             else (None if cond_op in ("è nullo", "non è nullo") else cond_val))
                    st.session_state.table_conditions.append((cond_col, cond_op, value))
                    st.rerun()

            conditions = st.session_state.table_conditions
            if conditions:
                logic = st.radio("Combina condizioni con", ["and", "or"], horizontal=True)
                st.write(" • " + f" **{logic.upper()}** ".join(
                    f"`{c}` {o} `{v}`" if v is not None else f"`{c}` {o}" for c, o, v in conditions))
                if st.button("🗑️ Svuota condizioni"):
                    st.session_state.table_conditions = []
                    st.rerun()

                selected_ids = dt.select_ids_by_conditions(df, conditions, logic=logic)
                st.info(f"**{len(selected_ids)}** nodi selezionati dalla condizione.")
                if selected_ids:
                    st.dataframe(df[df[dt.NODE_ID_COL].isin(selected_ids)],
                                  width="stretch", height=200)
                    if st.button(f"❌ Elimina i {len(selected_ids)} nodi selezionati dal grafo attivo"):
                        newG = pipeline.remove_nodes(G, selected_ids)
                        _activate_graph(pipeline, newG,
                                         f"{st.session_state.current_graph_name}_ripulita")
                        st.session_state.nodes_table_df = None
                        st.session_state.table_conditions = []
                        st.success(f"Rimossi {len(selected_ids)} nodi (e gli edge incidenti). "
                                   f"Nuova rete: {newG.number_of_nodes()} nodi, {newG.number_of_edges()} edge.")
                        st.rerun()

    # --- tabella edge ---
    st.markdown("---")
    with st.expander("Tabella edge della rete attiva"):
        if st.button("Genera tabella edge"):
            st.session_state.edges_table_df = pipeline.edges_table(G)
        if st.session_state.get("edges_table_df") is not None:
            st.dataframe(st.session_state.edges_table_df, width="stretch", height=300)
            st.download_button("📤 Esporta tabella edge per GUI Grafici (.csv)",
                               st.session_state.edges_table_df.to_csv(index=False).encode("utf-8"),
                               file_name="edge_rete.csv", mime="text/csv",
                               key="export_edges_csv_guigrafici")

# ------------------------------------------------------------------
# Metriche
# ------------------------------------------------------------------
with tab_metrics:
    st.subheader("Metriche strutturali")
    entropy_attr = st.selectbox("Attributo per l'entropia di vicinato",
                                 _pick(NODE_GROUP, ("category", "type", "ambito")))
    community_method = st.selectbox("Metodo community detection", ["louvain", "greedy_modularity", "label_propagation"])

    if st.button("Calcola metriche"):
        m = pipeline.compute_metrics(G, entropy_attribute=entropy_attr, community_method=community_method)
        st.session_state.last_metrics = m

    if "last_metrics" in st.session_state:
        m = st.session_state.last_metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Nodi", m["densita"]["n_nodi"])
        c2.metric("Legami", m["densita"]["n_edge"])
        c3.metric("Densità (link/nodi)", round(m["densita"]["densita_links_su_nodi"], 3))
        c4.metric("Densità standard", round(m["densita"]["densita_standard_0_1"], 4))

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Diametro (comp. maggiore)", m["diametro"]["diametro_componente_maggiore"])
        c6.metric("N. componenti", m["diametro"]["n_componenti"])
        c7.metric("N. comunità", m["n_comunita"])
        c8.metric("Modularità", round(m["modularita"], 3) if m["modularita"] else "N/D")

        c9, c10, c11 = st.columns(3)
        c9.metric("Entropia media di vicinato", round(m["entropia_media"], 3))
        c10.metric("Clustering medio", round(m["clustering"]["clustering_medio"], 3))
        c11.metric("Transitività", round(m["clustering"]["transitivita"], 3))

        node_labels = {n: G.nodes[n].get("label", n) for n in G.nodes()}
        col_deg, col_btw = st.columns(2)
        with col_deg:
            st.markdown("**Top 15 nodi per degree**")
            deg_items = sorted(m["degree"]["per_nodo"].items(), key=lambda kv: kv[1], reverse=True)[:15]
            st.dataframe(pd.DataFrame([{"Nodo": node_labels.get(n, n), "Degree": d} for n, d in deg_items]))
        with col_btw:
            st.markdown("**Top 15 broker per betweenness**")
            btw_items = sorted(m["betweenness_per_nodo"].items(), key=lambda kv: kv[1], reverse=True)[:15]
            st.dataframe(pd.DataFrame([{"Nodo": node_labels.get(n, n), "Betweenness": round(b, 4)}
                                        for n, b in btw_items]))

        st.markdown("**Metriche per comunità** (densità/entropia ristrette a ogni comunità)")
        st.dataframe(pd.DataFrame([{"Comunità": c, **vals} for c, vals in m["per_comunita"].items()]))

    st.markdown("---")
    with st.expander("🧭 Densità/entropia a granularità multiple (con export Excel per grafici)"):
        st.caption("Scegli a quali livelli calcolare le metriche (rete intera, per anno, per "
                   "comunità, per valore di un attributo, combinazioni anno×gruppo, o una "
                   "porzione filtrata a piacere). Il risultato è una tabella lunga — una riga "
                   "per gruppo — con densità, entropia di vicinato, diversità di composizione, "
                   "indice E-I, centralizzazione, Gini ecc., scaricabile come Excel con "
                   "fogli pivot già pronti per i grafici.")

        col_g1, col_g2, col_g3 = st.columns(3)
        with col_g1:
            gran_attr = st.selectbox("Attributo per gruppi/entropie",
                                      _pick(NODE_GROUP, ("category", "type", "ambito")), key="gran_attr")
        with col_g2:
            gran_year_mode = st.selectbox("Modalità per anno", ["snapshot", "cumulative"],
                                           key="gran_year_mode")
        with col_g3:
            gran_comm = st.selectbox("Comunità", ["louvain", "greedy_modularity"],
                                      key="gran_comm")

        scope_labels = {
            "Tutta la rete": "rete",
            "Per comunità": "comunita",
            f"Per valore di '{gran_attr}'": f"attributo:{gran_attr}",
            "Per anno": "anno",
            f"Anno × '{gran_attr}'": f"anno_x_attributo:{gran_attr}",
            "Anno × comunità": "anno_x_comunita",
            "Selezione manuale (una 'zona' scelta a mano)": "selezione_manuale",
        }
        gran_scopes = st.multiselect("Granularità da calcolare", list(scope_labels),
                                      default=["Tutta la rete", "Per anno", "Per comunità"],
                                      key="gran_scopes")

        gran_manual_ids = None
        if "Selezione manuale (una 'zona' scelta a mano)" in gran_scopes:
            gran_node_labels = {n: str(G.nodes[n].get("label", n)) for n in G.nodes()}
            gran_manual_labels = st.multiselect(
                "Nodi della selezione manuale", sorted(gran_node_labels.values()), key="gran_manual_labels")
            gran_manual_ids = [n for n, lab in gran_node_labels.items() if lab in gran_manual_labels]

        st.markdown("**Porzione di rete filtrata (opzionale)**")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            gran_filt_attr = st.selectbox("Filtra per",
                                           [None] + _pick(NODE_GROUP, ("type", "category", "ambito")),
                                           key="gran_filt_attr")
        gran_custom = None
        if gran_filt_attr:
            with col_f2:
                gran_filt_vals = st.multiselect(
                    "Valori", sorted({str(G.nodes[n].get(gran_filt_attr))
                                       for n in G.nodes() if G.nodes[n].get(gran_filt_attr)}),
                    key="gran_filt_vals")
            if gran_filt_vals:
                gran_custom = [{"nome": f"{gran_filt_attr}={'/'.join(gran_filt_vals)}",
                                 "criteria": {gran_filt_attr: gran_filt_vals}}]

        gran_ready = gran_scopes and (
            "Selezione manuale (una 'zona' scelta a mano)" not in gran_scopes or gran_manual_ids)
        if st.button("Calcola metriche a granularità multiple") and gran_ready:
            st.session_state.gran_df = pipeline.granular_report(
                G, [scope_labels[s] for s in gran_scopes],
                entropy_attribute=gran_attr, community_method=gran_comm,
                year_mode=gran_year_mode, custom_filters=gran_custom,
                manual_selection=gran_manual_ids)

        if st.session_state.get("gran_df") is not None:
            gran_df = st.session_state.gran_df
            st.dataframe(gran_df, width="stretch", height=350)
            xlsx_gran = os.path.join(tempfile.mkdtemp(), "metriche_granulari.xlsx")
            pipeline.export_granular_excel(gran_df, xlsx_gran)
            with open(xlsx_gran, "rb") as f:
                st.download_button("⬇️ Scarica Excel (dati + pivot + legenda)", f,
                                    file_name="metriche_granulari.xlsx")

    with st.expander("📐 Matrice di materialità (X × Y × dimensione)"):
        st.caption("Rilevanza stakeholder (X) × rilevanza organizzazione (Y) × contributo (dimensione). "
                   "I dati attuali non hanno colonne di rilevanza dedicate: scegli tu quali attributi "
                   "numerici usare come proxy (le colonne calcolate compaiono dopo 'Genera tabella nodi' "
                   "nella tab Tabella dati, che le scrive sul grafo).")
        mat_attrs = _pick(NODE_NUMERIC, ("degree", "degree_pesato", "betweenness", "entropia", "importo"))
        if len(mat_attrs) < 2:
            st.info("Servono almeno due attributi numerici sui nodi: genera prima la tabella "
                     "nodi (tab Tabella dati → Genera tabella nodi) o carica una rete con "
                     "colonne numeriche.")
        else:
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            with col_m1:
                mat_x = st.selectbox("X", mat_attrs, index=0, key="mat_x")
            with col_m2:
                mat_y = st.selectbox("Y", mat_attrs, index=1, key="mat_y")
            with col_m3:
                mat_size = st.selectbox("Dimensione", [None] + mat_attrs, key="mat_size")
            with col_m4:
                mat_group = st.selectbox("Raggruppa per", [None] + _pick(NODE_CATEGORICAL, ("category", "type", "ambito")),
                                          key="mat_group")
        if len(mat_attrs) >= 2 and st.button("Calcola matrice di materialità"):
            rows_mat = pipeline.materiality(G, mat_x, mat_y, size_attr=mat_size,
                                             group_by=mat_group)
            if not rows_mat:
                st.warning("Nessun valore numerico per gli attributi scelti: genera prima "
                           "le colonne calcolate (tab Tabella dati → Genera tabella nodi).")
            else:
                st.session_state.mat_rows = rows_mat
                png_mat = os.path.join(tempfile.mkdtemp(), "materialita.png")
                pipeline.plot_materiality(rows_mat, png_mat, x_label=mat_x, y_label=mat_y)
                st.session_state.mat_png = png_mat
        if st.session_state.get("mat_rows"):
            if st.session_state.get("mat_png") and os.path.exists(st.session_state.mat_png):
                st.image(st.session_state.mat_png)
            st.dataframe(pd.DataFrame(st.session_state.mat_rows), width="stretch", height=250)

    with st.expander("🛡️ Robustezza / dipendenza da nodi chiave (dimensione Health)"):
        rob_strategy = st.selectbox("Strategia di rimozione",
                                     ["degree", "degree_pesato", "betweenness", "random"],
                                     key="rob_strategy")
        col_r1, col_r2 = st.columns(2)

        with col_r1:
            st.markdown("**Dipendenza dai singoli nodi**")
            st.caption("Effetto della rimozione di UN nodo alla volta (i più centrali).")
            rob_topn = st.slider("Quanti nodi analizzare", 3, 30, 10)
            if st.button("Calcola dipendenza"):
                rows = pipeline.key_node_dependency(G, top_n=rob_topn, strategy=rob_strategy)
                st.session_state.rob_dependency = pd.DataFrame(rows).drop(columns=["node_id"])
            if st.session_state.get("rob_dependency") is not None:
                st.dataframe(st.session_state.rob_dependency, width="stretch")

        with col_r2:
            st.markdown("**Simulazione di attacco progressivo**")
            st.caption("Rimozione progressiva dei nodi più centrali: confronta con "
                       "'random' per misurare la ridondanza della rete.")
            if st.button("Simula attacco"):
                rows = pipeline.attack_simulation(G, strategy=rob_strategy)
                st.session_state.rob_attack = pd.DataFrame(rows)
            if st.session_state.get("rob_attack") is not None:
                df_att = st.session_state.rob_attack
                st.line_chart(df_att.set_index("frazione_rimossa")[["dim_componente_maggiore",
                                                                     "n_componenti"]])
                st.dataframe(df_att, width="stretch", height=200)

    st.markdown("---")
    st.markdown("#### Metriche avanzate")
    st.caption("Analisi puntuali da lanciare manualmente (non un report automatico) — vedi "
               "core/advanced_metrics.py.")

    with st.expander("🧭 Centralità aggiuntive (eigenvector, pagerank, closeness) + correlazione"):
        if st.button("Calcola centralità aggiuntive"):
            st.session_state.extra_cent = pipeline.extra_centralities(G)
            st.session_state.cent_corr = pipeline.centrality_correlation(G)
        if st.session_state.get("extra_cent"):
            ec = st.session_state.extra_cent
            node_labels_ec = {n: G.nodes[n].get("label", n) for n in G.nodes()}
            col_e1, col_e2, col_e3 = st.columns(3)
            for col, (nome, vals) in zip((col_e1, col_e2, col_e3), ec.items()):
                with col:
                    st.markdown(f"**Top 10 per {nome}**")
                    top = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)[:10]
                    st.dataframe(pd.DataFrame([{"Nodo": node_labels_ec.get(n, n), nome: round(v, 4)}
                                                for n, v in top]), width="stretch", height=250)
            st.markdown("**Correlazione tra misure di centralità** (1 = ridondanti)")
            st.dataframe(st.session_state.cent_corr.round(3), width="stretch")

    with st.expander("🕳️ k-core (nucleo strutturale della rete)"):
        st.caption("Il k-core è il sottografo massimale in cui ogni nodo ha almeno k legami "
                   "verso altri nodi del sottografo. Dove la dimensione smette di calare "
                   "bruscamente al crescere di k ('plateau') indica il nucleo più coeso.")
        if st.button("Calcola k-core al variare di k"):
            st.session_state.kcore_plateau = pipeline.k_core_plateau(G)
        if st.session_state.get("kcore_plateau") is not None:
            plateau = st.session_state.kcore_plateau
            st.dataframe(plateau, width="stretch", height=200)
            if not plateau.empty:
                st.line_chart(plateau.set_index("k")[["n_nodi", "n_edge"]])
                k_sel = st.selectbox("Estrai il k-core a k =", plateau["k"].tolist(), key="kcore_k")
                if st.button("Attiva il k-core selezionato come rete corrente"):
                    sub = pipeline.k_core_subgraph(G, int(k_sel))
                    _activate_graph(pipeline, sub, f"{st.session_state.current_graph_name}_kcore{k_sel}")
                    st.rerun()

    with st.expander("🌉 Misure di Burt (effective size, efficiency, constraint)"):
        st.caption("Effective size alto + constraint basso = il nodo collega gruppi altrimenti "
                   "non ridondanti tra loro (buon potenziale di brokeraggio).")
        if st.button("Calcola misure di Burt"):
            st.session_state.burt_df = pipeline.burt_measures(G)
        if st.session_state.get("burt_df") is not None:
            st.dataframe(st.session_state.burt_df.drop(columns=["node_id"]),
                          width="stretch", height=300)

    with st.expander("🔺 Triadi aperte / chiusura triadica"):
        st.caption("Quante triple di nodi connesse da due legami sono chiuse in un triangolo "
                   "(chiusura triadica) rispetto a quelle rimaste aperte, sull'intera rete e "
                   "per gruppo (per attributo o per comunità).")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            triad_mode = st.radio("Per gruppo", ["Nessuno (solo rete intera)", "Per attributo", "Per comunità"],
                                   key="triad_mode")
        with col_t2:
            triad_attr = None
            if triad_mode == "Per attributo":
                triad_attr = st.selectbox("Attributo", _pick(NODE_GROUP, ("category", "type")), key="triad_attr")
        if st.button("Calcola chiusura triadica"):
            st.session_state.triad_global = pipeline.triad_closure(G)
            if triad_mode == "Per attributo" and triad_attr:
                st.session_state.triad_group = pipeline.triad_closure_per_group(G, group_attr=triad_attr)
            elif triad_mode == "Per comunità":
                partition = metrics_mod.detect_communities(G)
                from core import advanced_metrics as adv_mod
                st.session_state.triad_group = adv_mod.triad_closure_per_group(G, partition=partition)
            else:
                st.session_state.triad_group = None
        if st.session_state.get("triad_global"):
            tg = st.session_state.triad_global
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Triangoli", tg["triangoli"])
            c2.metric("Triple totali", tg["triple_totali"])
            c3.metric("Triple aperte", tg["triple_aperte"])
            c4.metric("Tasso di chiusura", tg["tasso_chiusura"])
        if st.session_state.get("triad_group") is not None:
            st.dataframe(st.session_state.triad_group, width="stretch")

    with st.expander("🎯 Omofilia: matrice di mixing + test vs modello nullo"):
        st.caption("La matrice di mixing mostra su quali combinazioni di categorie cadono i "
                   "legami; il test confronta l'omofilia osservata (indice E-I) con quella "
                   "ottenuta rimescolando a caso l'attributo tra i nodi (modello nullo).")
        col_h1, col_h2 = st.columns(2)
        with col_h1:
            homo_attr = st.selectbox("Attributo", _pick(NODE_GROUP, ("category", "type", "ambito")),
                                      key="homo_attr")
        with col_h2:
            homo_reps = st.slider("Ripetizioni del modello nullo", 50, 1000, 200, 50, key="homo_reps")
        if homo_attr and st.button("Calcola mixing + test di omofilia"):
            st.session_state.mixing_df = pipeline.mixing_matrix(G, homo_attr)
            st.session_state.homo_result = pipeline.homophily_vs_null(G, homo_attr, n_reps=homo_reps)
        if st.session_state.get("mixing_df") is not None:
            st.dataframe(st.session_state.mixing_df, width="stretch")
        if st.session_state.get("homo_result"):
            hr = st.session_state.homo_result
            c1, c2, c3 = st.columns(3)
            c1.metric("E-I osservato", hr["osservato"])
            c2.metric("Media modello nullo", hr["media_nulla"])
            c3.metric("z-score", hr["z_score"])
            st.caption(f"**{hr['interpretazione']}** ({hr['n_ripetizioni']} ripetizioni). "
                       "|z| ≥ 1.96 = non spiegabile dal caso (soglia 5%).")

    with st.expander("🏷️ Specializzazione (indice HHI)"):
        st.caption("Quanto ogni nodo (o gruppo) concentra i propri legami su poche categorie "
                   "dell'attributo scelto, invece di distribuirli — 1 = tutto su una categoria, "
                   "1/k = equidistribuito su k categorie.")
        spec_attr = st.selectbox("Attributo dei vicini", _pick(NODE_GROUP, ("category", "type")),
                                  key="spec_attr")
        spec_group_by = st.selectbox("Aggrega per gruppo (opzionale)",
                                      [None] + _pick(NODE_GROUP, ("category", "type")), key="spec_group_by")
        if spec_attr and st.button("Calcola specializzazione"):
            if spec_group_by:
                st.session_state.spec_df = pipeline.specialization_per_group(G, spec_group_by, spec_attr)
            else:
                node_labels_sp = {n: G.nodes[n].get("label", n) for n in G.nodes()}
                per_node = pipeline.specialization_per_node(G, spec_attr)
                st.session_state.spec_df = pd.DataFrame(
                    [{"Nodo": node_labels_sp.get(n, n), "hhi": v} for n, v in per_node.items()
                     if v is not None]).sort_values("hhi", ascending=False)
        if st.session_state.get("spec_df") is not None:
            st.dataframe(st.session_state.spec_df, width="stretch", height=300)

    with st.expander("📉 Concentrazione: Gini generalizzato + curva di Lorenz"):
        st.caption("Applicabile a qualunque misura numerica calcolata sopra (degree, "
                   "betweenness, eigenvector, ...): quanto è concentrata in pochi nodi.")
        conc_source = st.radio("Misura", ["Degree", "Degree pesato"], key="conc_source", horizontal=True)
        if st.button("Calcola concentrazione"):
            values = [d for _, d in G.degree(weight="weight" if conc_source == "Degree pesato" else None)]
            st.session_state.conc_gini = pipeline.gini(values)
            st.session_state.conc_lorenz = pipeline.lorenz_curve(values)
        if st.session_state.get("conc_lorenz") is not None:
            st.metric("Coefficiente di Gini", st.session_state.conc_gini)
            st.line_chart(st.session_state.conc_lorenz.set_index("frazione_popolazione"))

    with st.expander("📈 Distribuzione dei gradi (scala log-log)"):
        if st.button("Calcola distribuzione dei gradi"):
            st.session_state.degdist_df = pipeline.degree_distribution_loglog(G)
        if st.session_state.get("degdist_df") is not None:
            dd = st.session_state.degdist_df
            if dd.empty:
                st.info("Nessun nodo con grado > 0.")
            else:
                st.scatter_chart(dd.set_index("log_grado")[["log_n_nodi"]])
                st.dataframe(dd, width="stretch", height=200)

# ------------------------------------------------------------------
# Analisi temporale
# ------------------------------------------------------------------
with tab_temporal:
    st.subheader("Analisi nel tempo")
    st.caption("Richiede un grafo con attributo 'anno' sugli edge (tipicamente la rete bipartita originale).")
    mode = st.radio("Modalità", ["snapshot", "cumulative"], help="snapshot = solo edge di quell'anno; "
                     "cumulative = tutti gli edge fino a quell'anno")

    base_graph = pipeline.G_bipartite if pipeline.G_bipartite is not None else G
    if st.button("Calcola metriche nel tempo"):
        mot = pipeline.metrics_over_time(base_graph, mode=mode)
        st.session_state.mot = mot

    if "mot" in st.session_state:
        mot = st.session_state.mot
        rows = []
        for y, r in sorted(mot.items()):
            rows.append({
                "Anno": y, "Nodi": r["densita"]["n_nodi"], "Legami": r["densita"]["n_edge"],
                "Densità (link/nodi)": round(r["densita"]["densita_links_su_nodi"], 3),
                "Entropia media": round(r["entropia_media"], 3), "N. comunità": r["n_comunita"],
            })
        df = pd.DataFrame(rows)
        st.dataframe(df)
        st.line_chart(df.set_index("Anno")[["Densità (link/nodi)", "Entropia media"]])

        # --- lettura del ciclo di vita ---
        if st.button("📖 Leggi la fase del ciclo di vita (IPARL)"):
            st.session_state.lifecycle = pipeline.read_lifecycle(mot)
        if st.session_state.get("lifecycle"):
            lc = st.session_state.lifecycle
            st.metric("Fase proposta", lc["fase"])
            st.caption(lc["motivazione"] + " (Criteri espliciti e regolabili: "
                       f"{lc['parametri']}. Proposta euristica di supporto, non un verdetto.)")
            st.dataframe(pd.DataFrame(lc["indicatori"]), width="stretch")

    # --- proiezione per anno ---
    st.markdown("---")
    st.subheader("Proiezione per anno")
    st.caption("Divide il bipartito per anno e proietta ogni sottografo annuale: "
               "l'anno vive sugli edge del bipartito, non sulle proiezioni.")
    col_p1, col_p2, col_p3 = st.columns(3)
    with col_p1:
        pby_side = st.selectbox("Lato da proiettare", ["ente", "progetto"], key="pby_side",
                               format_func=_SIDE_LABEL.get)
    with col_p2:
        pby_weight = st.selectbox("Modalità peso", ["count", "sum_weight", "jaccard"], key="pby_weight")
    with col_p3:
        pby_mode = st.selectbox("Modalità temporale", ["snapshot", "cumulative"], key="pby_mode")

    if st.button("Calcola proiezioni per anno"):
        if pipeline.G_bipartite is None:
            st.error("Serve il grafo bipartito: carica i file Excel dalla barra laterale.")
        else:
            st.session_state.proj_by_year = pipeline.get_projection_by_year(
                pby_side, weight_mode=pby_weight, mode=pby_mode)

    if st.session_state.get("proj_by_year"):
        pby = st.session_state.proj_by_year
        st.dataframe(pd.DataFrame([
            {"Anno": y, "Nodi": g.number_of_nodes(), "Legami": g.number_of_edges()}
            for y, g in sorted(pby.items())]))
        pby_year = st.selectbox("Anno da attivare", sorted(pby.keys()), key="pby_year")
        if st.button("Attiva la proiezione di questo anno come rete corrente"):
            _activate_graph(pipeline, pby[pby_year], f"projection_{pby_side}_{pby_year}")
            st.rerun()

    # --- confronto tra due anni ---
    st.markdown("---")
    st.subheader("Confronto tra due snapshot")
    st.caption("Nodi entrati/usciti, edge entrati/usciti e differenza di degree tra due anni.")
    # key=str: dopo una fusione di nodi un edge può avere anno composito
    # ("2023, 2024") accanto agli interi, e l'ordinamento misto fallirebbe
    years_available = sorted({data.get("anno") for _, _, data in base_graph.edges(data=True)} - {None},
                              key=str)
    if len(years_available) < 2:
        st.info("Servono almeno due anni distinti sugli edge della rete bipartita.")
    else:
        col_y1, col_y2, col_y3 = st.columns(3)
        with col_y1:
            cmp_y1 = st.selectbox("Anno 'prima'", years_available, index=0, key="cmp_y1")
        with col_y2:
            cmp_y2 = st.selectbox("Anno 'dopo'", years_available,
                                   index=len(years_available) - 1, key="cmp_y2")
        with col_y3:
            cmp_mode = st.selectbox("Modalità", ["snapshot", "cumulative"], key="cmp_mode")

        if st.button("Confronta i due anni"):
            graphs_by_year = pipeline.split_by_year(base_graph, mode=cmp_mode)
            G1, G2 = graphs_by_year[cmp_y1], graphs_by_year[cmp_y2]
            result = pipeline.compare(G1, G2, labels=(str(cmp_y1), str(cmp_y2)))
            st.session_state.cmp_result = result
            st.session_state.cmp_table = pipeline.comparison_table(result, G1, G2)

        if st.session_state.get("cmp_result"):
            r = st.session_state.cmp_result
            l1, l2 = r["labels"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(f"Nodi {l1} → {l2}",
                      f'{r["sintesi"]["n_nodi"][l1]} → {r["sintesi"]["n_nodi"][l2]}',
                      delta=r["sintesi"]["n_nodi"]["delta"])
            c2.metric(f"Legami {l1} → {l2}",
                      f'{r["sintesi"]["n_edge"][l1]} → {r["sintesi"]["n_edge"][l2]}',
                      delta=r["sintesi"]["n_edge"]["delta"])
            c3.metric("Nodi entrati", len(r["nodi"]["entrati"]))
            c4.metric("Nodi usciti", len(r["nodi"]["usciti"]))
            dens = r["sintesi"]["densita_links_su_nodi"]
            st.metric("Densità (link/nodi)", f"{dens[l1]:.3f} → {dens[l2]:.3f}",
                      delta=round(dens["delta"], 3))
            st.markdown("**Dettaglio per nodo** (comuni, entrati, usciti — ordinati per delta degree)")
            st.dataframe(st.session_state.cmp_table, width="stretch", height=300)

    # --- animazione dell'evoluzione ---
    st.markdown("---")
    st.subheader("🎬 Animazione dell'evoluzione nel tempo")
    st.caption("GIF con un frame per anno e layout fisso (i nodi non si spostano tra i frame): "
               "si vede la rete accendersi e addensarsi. Scaricabile e riusabile in report/slide.")
    col_a1, col_a2, col_a3, col_a4 = st.columns(4)
    with col_a1:
        anim_target = st.selectbox("Rete da animare",
                                    ["bipartita", "proiezione ente", "proiezione progetto"],
                                    key="anim_target")
    with col_a2:
        anim_mode = st.selectbox("Modalità", ["cumulative", "snapshot"], key="anim_mode",
                                  help="cumulative = la rete cresce anno su anno; "
                                       "snapshot = solo gli edge di ciascun anno")
    with col_a3:
        _bip_node_cat = (introspect.graph_attributes(pipeline.G_bipartite)["node_categorical"]
                          if pipeline.G_bipartite is not None else [])
        anim_color = st.selectbox("Colora per",
                                   _pick(_bip_node_cat, ("category", "type", "ambito", "bipartite")),
                                   key="anim_color")
    with col_a4:
        anim_fps = st.slider("Frame al secondo", 0.25, 4.0, 1.0, 0.25, key="anim_fps")
    anim_ghost = st.checkbox("Mostra i nodi non ancora attivi come 'fantasmi' grigi", value=True)

    if st.button("Genera animazione"):
        if pipeline.G_bipartite is None:
            st.error("Serve il grafo bipartito: carica i file Excel dalla barra laterale.")
        else:
            anim_on = {"bipartita": None, "proiezione ente": "ente",
                       "proiezione progetto": "progetto"}[anim_target]
            gif_path = os.path.join(tempfile.mkdtemp(), "evoluzione.gif")
            with st.spinner("Calcolo layout e disegno dei frame..."):
                pipeline.animate(gif_path, mode=anim_mode, on=anim_on,
                                  color_by=anim_color, fps=anim_fps,
                                  show_inactive=anim_ghost)
            st.session_state.anim_gif = gif_path

    if st.session_state.get("anim_gif"):
        st.image(st.session_state.anim_gif)
        with open(st.session_state.anim_gif, "rb") as f:
            st.download_button("Scarica evoluzione.gif", f, file_name="evoluzione.gif")

# ------------------------------------------------------------------
# Link prediction
# ------------------------------------------------------------------
with tab_predict:
    st.subheader("Suggerimento di nuovi legami (link prediction)")
    st.caption("Metodi classici di similarità strutturale: coppie NON collegate con molti "
               "vicini in comune sono candidate a collegarsi (es. potenziali collaborazioni "
               "tra enti). Da usare sulle PROIEZIONI (ente-ente): sul bipartito due nodi "
               "dello stesso lato non sono mai adiacenti e i punteggi degradano.")

    from core import link_prediction as lp_mod
    col_lp1, col_lp2 = st.columns(2)
    with col_lp1:
        lp_method = st.selectbox("Metodo", list(lp_mod.METHODS.keys()),
                                  index=list(lp_mod.METHODS.keys()).index("adamic_adar"),
                                  key="lp_method")
    with col_lp2:
        lp_topk = st.slider("Quanti suggerimenti", 5, 100, 20, 5, key="lp_topk")

    if st.button("Suggerisci nuovi legami sulla rete attiva"):
        try:
            st.session_state.lp_preds = pipeline.predict_links(G, method=lp_method, top_k=lp_topk)
        except ValueError as e:
            st.error(str(e))

    if st.session_state.get("lp_preds") is not None:
        preds = st.session_state.lp_preds
        if not preds:
            st.info("Nessuna coppia candidata con punteggio > 0.")
        else:
            st.dataframe(pd.DataFrame(preds)[["label_u", "label_v", "score"]],
                          width="stretch", height=350)

    st.markdown("---")
    st.subheader("Validazione con hold-out temporale")
    st.caption("Allena sulla rete cumulativa fino all'anno precedente e verifica quanti dei "
               "nuovi legami dell'anno di test erano tra i suggeriti (precision@k). "
               "Richiede il grafo bipartito con gli anni.")
    if pipeline.G_bipartite is None:
        st.info("Serve il grafo bipartito: carica i file Excel.")
    else:
        anni_lp = sorted({data.get("anno") for _, _, data in pipeline.G_bipartite.edges(data=True)}
                          - {None}, key=str)
        if len(anni_lp) < 2:
            st.info("Servono almeno due anni distinti sugli edge.")
        else:
            col_h1, col_h2 = st.columns(2)
            with col_h1:
                lp_year = st.selectbox("Anno di test", anni_lp[1:], index=len(anni_lp) - 2,
                                        key="lp_year")
            with col_h2:
                lp_side = st.selectbox("Proiezione", ["ente", "progetto"], key="lp_side",
                                       format_func=_SIDE_LABEL.get)
            if st.button("Valuta il metodo sull'anno di test"):
                try:
                    st.session_state.lp_holdout = pipeline.link_prediction_holdout(
                        lp_year, on=lp_side, method=lp_method, top_k=lp_topk)
                except ValueError as e:
                    st.error(str(e))
            if st.session_state.get("lp_holdout"):
                h = st.session_state.lp_holdout
                c1, c2, c3 = st.columns(3)
                c1.metric("Precision@k", h["precision_at_k"])
                c2.metric("Previsioni azzeccate", h["n_hits"])
                c3.metric("Nuovi legami osservati", h["n_nuovi_legami_osservati"])
                if h["hits"]:
                    st.markdown("**Legami previsti correttamente**")
                    st.dataframe(pd.DataFrame(h["hits"])[["label_u", "label_v", "score"]],
                                  width="stretch")

    st.markdown("---")
    st.subheader("ML supervisionato (impara dalle transizioni anno→anno)")
    st.caption("Allena una regressione logistica sulle feature strutturali (i punteggi dei "
               "metodi classici + degree) usando i legami effettivamente nati anno su anno, "
               "poi suggerisce le coppie più probabili sull'ultima rete cumulativa. "
               "Usa scikit-learn se installato, altrimenti l'implementazione interna.")
    if st.button("Allena e suggerisci (ML)"):
        try:
            with st.spinner("Training sulle transizioni anno→anno..."):
                st.session_state.lp_ml = pipeline.supervised_link_prediction(
                    on=st.session_state.get("lp_side", "ente"), top_k=lp_topk)
        except ValueError as e:
            st.error(str(e))
    if st.session_state.get("lp_ml"):
        ml = st.session_state.lp_ml
        st.caption(f"Modello: {ml['modello']} — {ml['n_esempi']} esempi "
                   f"({ml['n_positivi']} positivi), anni {ml['anni_usati']}.")
        if ml["previsioni"]:
            st.dataframe(pd.DataFrame(ml["previsioni"])[["label_u", "label_v", "probabilita"]],
                          width="stretch", height=300)
        else:
            st.info("Nessuna coppia candidata sull'ultima rete.")

# ------------------------------------------------------------------
# Simulazioni (dinamiche su rete + framework a classi di nodi)
# ------------------------------------------------------------------
with tab_sim:
    st.subheader("Simulazioni sulla rete attiva")
    st.caption("Modelli classici di dinamica su rete (Granovetter, Ising, Schelling) e il "
               "framework a classi di nodi con regole (vedi core/simulation.py). "
               "Le prime tre girano sulla rete corrente; il framework genera una rete nuova.")
    G_sim = G
    if isinstance(G_sim, nx.MultiGraph):
        st.warning("La rete corrente è un multigrafo: per queste simulazioni componila "
                   "prima con 'Unisci tutto' nella tab Multiplex.")

    col_s1, col_s2, col_s3 = st.columns(3)

    with col_s1:
        st.markdown("**Cascata di Granovetter** (adozione a soglia)")
        gr_thr = st.slider("Soglia (frazione vicini adottanti)", 0.0, 1.0, 0.3, 0.05)
        node_labels_sim = {n: str(G_sim.nodes[n].get("label", n)) for n in G_sim.nodes()}
        gr_seed_lab = st.selectbox("Nodo seme iniziale", sorted(node_labels_sim.values()),
                                    key="gr_seed")
        if st.button("Simula cascata") and not isinstance(G_sim, nx.MultiGraph):
            seed_id = [n for n, lab in node_labels_sim.items() if lab == gr_seed_lab][0]
            st.session_state.sim_gr = pipeline.granovetter(G_sim, gr_thr, [seed_id])
        if st.session_state.get("sim_gr"):
            r = st.session_state.sim_gr
            st.metric("Frazione finale adottanti", r["frazione_finale"])
            st.line_chart(pd.DataFrame({"adottanti": r["storia"]}))

    with col_s2:
        st.markdown("**Ising / Glauber** (consenso-polarizzazione)")
        is_beta = st.slider("Beta (conformismo)", 0.1, 5.0, 1.0, 0.1)
        is_steps = st.slider("Passi", 500, 10000, 2000, 500)
        if st.button("Simula Ising") and not isinstance(G_sim, nx.MultiGraph):
            st.session_state.sim_is = pipeline.ising(G_sim, beta=is_beta, steps=is_steps)
        if st.session_state.get("sim_is"):
            r = st.session_state.sim_is
            st.metric("Magnetizzazione finale", r["magnetizzazione"])
            st.line_chart(pd.DataFrame({"magnetizzazione": r["storia_magnetizzazione"]}))

    with col_s3:
        st.markdown("**Schelling** (migrazione/segregazione)")
        sc_tol = st.slider("Tolleranza (min frazione simili)", 0.0, 1.0, 0.5, 0.05)
        sc_empty = st.slider("Frazione nodi vuoti", 0.05, 0.5, 0.1, 0.05)
        if st.button("Simula Schelling") and not isinstance(G_sim, nx.MultiGraph):
            st.session_state.sim_sc = pipeline.schelling(G_sim, tolerance=sc_tol,
                                                          empty_fraction=sc_empty)
        if st.session_state.get("sim_sc"):
            r = st.session_state.sim_sc
            st.metric("Indice di segregazione", r["indice_segregazione"],
                      help="Frazione media di vicini della stessa classe")
            st.line_chart(pd.DataFrame({"segregazione": r["storia_indice"]}))

    st.markdown("---")
    st.markdown("**Framework a classi di nodi con regole** (truth-table preferenze; "
                "l'esempio A/B/C del brief è precompilato — vedi core/simulation.py per "
                "condizioni di accettazione e migrazione personalizzate)")
    default_prefs = ('{"A,A": ["a","b"], "A,B": ["a","b"], "A,C": ["a","b"],\n'
                     ' "B,A": ["b","c"], "B,B": ["b"],     "B,C": ["a","b"],\n'
                     ' "C,A": ["b","a"], "C,B": ["b","a"], "C,C": ["a","b"]}')
    col_r1, col_r2 = st.columns([2, 1])
    with col_r1:
        prefs_json = st.text_area("Preferenze {(classe_proponente,classe_ricevente): [tipi]}",
                                   default_prefs, height=110, key="rules_prefs")
    with col_r2:
        rules_n = st.number_input("Nodi per classe", 3, 200, 10)
        rules_steps = st.number_input("Passi", 50, 5000, 500, 50)
    if st.button("Esegui simulazione a regole"):
        import json as json_mod
        from core.simulation import SimulationRules
        try:
            raw = json_mod.loads(prefs_json)
            prefs = {tuple(k.split(",")): v for k, v in raw.items()}
            classes = sorted({c for k in prefs for c in k})
            types = sorted({t for v in prefs.values() for t in v})
            rules = SimulationRules(node_classes=classes, edge_types=types,
                                     preferences=prefs)
            Gr = pipeline.simulate_rules(rules, n_per_class={c: int(rules_n) for c in classes},
                                          steps=int(rules_steps))
            st.session_state.sim_rules_graph = Gr
        except (ValueError, KeyError) as e:
            st.error(f"Preferenze non valide: {e}")
    if st.session_state.get("sim_rules_graph") is not None:
        Gr = st.session_state.sim_rules_graph
        from core import multiplex as mx_mod
        st.success(f"Rete simulata: {Gr.number_of_nodes()} nodi, {Gr.number_of_edges()} edge "
                   f"su layer {mx_mod.get_layers(Gr)}.")
        st.dataframe(pd.DataFrame(mx_mod.layer_summary(Gr)))
        if st.button("Attiva la rete simulata come corrente (composta per tipo)"):
            flat = mx_mod.flatten(Gr, strategy="count", merge_scope="all")
            _activate_graph(pipeline, flat, "simulazione_regole")
            st.rerun()

    # --- nodi agentici (decisioni prese da un modello AI) ---
    st.markdown("---")
    with st.expander("🤖 Nodi agentici (accettazione decisa da un modello AI)"):
        from core import llm_agents
        st.caption("Le condizioni di ACCETTAZIONE della simulazione a regole vengono decise "
                   "da un modello linguistico, nodo per nodo, con budget di chiamate e cache. "
                   "Al modello va SOLO il contesto sintetico della simulazione (classi A/B/C, "
                   "conteggi di edge) — mai i tuoi dati. Con Ollama tutto resta sulla macchina.")

        col_a1, col_a2 = st.columns(2)
        with col_a1:
            llm_provider = st.selectbox("Provider", ["Ollama (locale, consigliato)",
                                                       "Claude API", "Gemini API"],
                                         key="llm_provider")
        provider_key = {"Ollama (locale, consigliato)": "ollama",
                         "Claude API": "claude", "Gemini API": "gemini"}[llm_provider]
        with col_a2:
            if provider_key == "ollama":
                installed = llm_agents.list_ollama_models()
                opts = installed or llm_agents.SUGGESTED_OLLAMA_MODELS
                llm_model = st.selectbox("Modello", opts, key="llm_model_ollama",
                                          help="Elenco filtrato ai modelli adatti "
                                               "(testo/JSON, no vision/embedding).")
                if not installed:
                    st.warning("Ollama non risponde su localhost:11434: avvialo con 'ollama serve'.")
            elif provider_key == "claude":
                llm_model = st.selectbox("Modello", llm_agents.SUGGESTED_CLAUDE_MODELS,
                                          key="llm_model_claude")
            else:
                llm_model = st.selectbox("Modello", llm_agents.SUGGESTED_GEMINI_MODELS,
                                          key="llm_model_gemini")

        llm_api_key = None
        if provider_key in ("claude", "gemini"):
            env_var = "ANTHROPIC_API_KEY" if provider_key == "claude" else "GEMINI_API_KEY"
            # Massima sicurezza (stessa scelta di pipeline video): la chiave si
            # incolla SEMPRE qui, mai letta automaticamente da .env/variabili
            # d'ambiente anche se presenti — vale solo per questa sessione,
            # non viene mai salvata su disco.
            llm_api_key = st.text_input(f"Chiave API ({env_var})", type="password",
                                         key="llm_api_key",
                                         help="Usata solo in questa sessione, mai salvata su disco.")

        if st.button("Prova connessione"):
            try:
                client = llm_agents.make_client(provider_key, llm_model, api_key=llm_api_key)
                risposta = client.chat("Rispondi con una sola parola.", "Dimmi ok.")
                st.success(f"{client.nome} risponde: {risposta.strip()[:80]}")
            except Exception as e:
                st.error(f"Connessione fallita: {e}")

        llm_personas = st.text_area(
            "Comportamento per classe (opzionale, una riga per classe: 'Classe: descrizione')",
            "A: molto selettivo, accetta solo legami che lo rendono più centrale\n"
            "B: collaborativo, accetta quasi tutto\n"
            "C: prudente, preferisce legami deboli", height=80, key="llm_personas")
        llm_budget = st.slider("Budget massimo di chiamate al modello", 5, 200, 30, 5,
                                help="Oltre il budget le decisioni usano il default (accetta); "
                                     "situazioni identiche sono in cache e non richiamano il modello.")

        if st.button("🤖 Esegui simulazione con accettazione AI"):
            import json as json_mod
            from core.simulation import SimulationRules
            try:
                raw = json_mod.loads(st.session_state.get("rules_prefs", default_prefs))
                prefs = {tuple(k.split(",")): v for k, v in raw.items()}
                classes = sorted({c for k in prefs for c in k})
                types = sorted({t for v in prefs.values() for t in v})
                personas = {}
                for riga in llm_personas.splitlines():
                    if ":" in riga:
                        cl, desc = riga.split(":", 1)
                        personas[cl.strip()] = desc.strip()
                client = llm_agents.make_client(provider_key, llm_model, api_key=llm_api_key)
                acceptance, agente = llm_agents.agentic_acceptance_rules(
                    client, classes, types, personas=personas, max_calls=llm_budget)
                rules = SimulationRules(node_classes=classes, edge_types=types,
                                         preferences=prefs, acceptance=acceptance)
                with st.spinner(f"Simulazione con {client.nome} (max {llm_budget} chiamate)..."):
                    Gr2 = pipeline.simulate_rules(
                        rules, n_per_class={c: int(rules_n) for c in classes},
                        steps=int(rules_steps))
                st.session_state.sim_rules_graph = Gr2
                st.session_state.sim_agent_log = agente.log
                st.success(f"Fatto: {agente.calls} chiamate al modello, "
                           f"{len(agente.log)} decisioni registrate.")
            except Exception as e:
                st.error(f"Simulazione agentica fallita: {e}")

        if st.session_state.get("sim_agent_log"):
            st.markdown("**Log delle decisioni dell'agente** (con i motivi)")
            st.dataframe(pd.DataFrame(st.session_state.sim_agent_log),
                          width="stretch", height=250)

# ------------------------------------------------------------------
# Export & Report
# ------------------------------------------------------------------
with tab_export:
    st.subheader("Esporta la rete corrente")
    st.caption("Usa lo stile/layout impostati in barra laterale (gli stessi della vista live qui sopra).")
    basename = st.text_input("Nome base file", value=st.session_state.current_graph_name or "rete")
    Gexport = st.session_state.get("view_graph") or _build_view_graph(G)

    if st.button("Esporta in tutti i formati (GEXF, GraphML, CSV, PNG, SVG, HTML)"):
        out_dir = tempfile.mkdtemp()
        export_pos = st.session_state.get("view_positions") if st.session_state.get("view_graph") is Gexport else None
        paths = pipeline.export(Gexport, out_dir, basename, positions=export_pos)
        st.session_state.export_paths = paths
        st.success("Export completato.")

    if "export_paths" in st.session_state:
        for fmt, path in st.session_state.export_paths.items():
            with open(path, "rb") as f:
                st.download_button(f"Scarica {fmt}", f, file_name=os.path.basename(path))

    st.markdown("---")
    with st.expander("🎯 Impatto EVPA (stime utente, opzionale)"):
        st.caption("Impatto netto = outcome × (1−deadweight) × (1−attribution) × (1−displacement), "
                   "drop-off annuo dal 2° anno. Le stime dei bias le fornisci tu (frazioni 0-1): "
                   "non sono calcolabili dai dati di rete. La tabella entra nel report.")
        impact_df_default = pd.DataFrame([
            {"nome": "", "outcome": 0.0, "deadweight": 0.0, "attribution": 0.0,
             "displacement": 0.0, "drop_off": 0.0, "years": 1}])
        impact_input = st.data_editor(
            st.session_state.get("impact_input_df", impact_df_default),
            num_rows="dynamic", key="impact_editor", width="stretch")
        if st.button("Calcola impatto netto"):
            righe = [r for r in impact_input.to_dict("records")
                     if r.get("nome") and r.get("outcome")]
            if not righe:
                st.warning("Inserisci almeno una riga con nome e outcome.")
            else:
                try:
                    st.session_state.impact_result = pipeline.impact_table(righe)
                    st.session_state.impact_input_df = impact_input
                except ValueError as e:
                    st.error(str(e))
        if st.session_state.get("impact_result"):
            res_imp = st.session_state.impact_result
            c1, c2 = st.columns(2)
            c1.metric("Totale outcome lordo", res_imp["totale_lordo"])
            c2.metric("Totale impatto netto", res_imp["totale_netto"])
            st.dataframe(pd.DataFrame(res_imp["righe"]), width="stretch")

    st.markdown("---")
    st.subheader("Genera report")
    st.caption("Il report include automaticamente ciò che hai già calcolato nelle altre tab: "
               "metriche (con broker, clustering, per-comunità), metriche nel tempo, "
               "animazione GIF dell'evoluzione, robustezza/dipendenza.")
    exec_summary = st.text_area("Executive summary (opzionale)", "")
    if st.button("Genera report HTML"):
        m = st.session_state.get("last_metrics") or pipeline.compute_metrics(Gexport)
        out_dir = tempfile.mkdtemp()
        png_path = os.path.join(out_dir, "network.png")
        report_pos = st.session_state.get("view_positions") if st.session_state.get("view_graph") is Gexport else None
        pipeline.export_png(Gexport, png_path, positions=report_pos)
        report_path = os.path.join(out_dir, "report.html")
        rob_att = st.session_state.get("rob_attack")
        rob_dep = st.session_state.get("rob_dependency")
        anim_gif = st.session_state.get("anim_gif")
        pipeline.build_report(
            report_path, G=Gexport, metrics=m,
            titolo="Report Network Analysis",
            dataset_nome=st.session_state.current_graph_name,
            network_png_path=png_path,
            metrics_by_year=st.session_state.get("mot"),
            executive_summary=exec_summary or None,
            evolution_gif_path=anim_gif if anim_gif and os.path.exists(anim_gif) else None,
            robustness_rows=rob_att.to_dict("records") if rob_att is not None else None,
            dependency_rows=rob_dep.to_dict("records") if rob_dep is not None else None,
            impact_rows=(st.session_state.impact_result["righe"]
                          if st.session_state.get("impact_result") else None),
        )
        with open(report_path, "rb") as f:
            st.download_button("Scarica report.html", f, file_name="report.html")
