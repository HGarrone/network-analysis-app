# Struttura del progetto

`core/` — libreria pura, ogni file una responsabilità, richiamabile da
script/notebook o dalla GUI:

```
core/
  config.py       # nomi colonne Excel, formula peso, palette base
  data_io.py      # caricamento Excel + costruzione grafo bipartito Ente↔Progetto;
                  # import da Gephi (GEXF) / Cytoscape (GraphML)
  filters.py       # filtri di selezione (costruiscono sotto-rete vera) e di
                  # visualizzazione (nascondono senza ricalcolare)
  ego.py            # ego-network generalizzata (nodo singolo o filtro per attributo),
                  # per gradi di distanza; pipeline.ego_on_root() = radice config.root_label
  projections.py    # proiezioni bipartite Ente-Ente / Progetto-Progetto;
                  # project_by_year = proiezione separata per ogni anno;
                  # node_filter = proiezione ristretta (es. rete delle fondazioni)
  metrics.py        # densità (sia link/nodi che standard), degree, betweenness
                  # (broker), clustering/transitività, diametro, entropia di
                  # vicinato, community detection (louvain), metriche per comunità
  granular.py       # densità/entropia a granularità componibili (rete, anno,
                  # comunità, attributo, anno×gruppo, filtri custom) con indice
                  # E-I, entropia di composizione, centralizzazione, Gini;
                  # export Excel dati+pivot+legenda per i grafici
  robustness.py     # dipendenza da nodi chiave e simulazione di attacco
                  # progressivo (dimensione Health: ridondanza/frammentazione)
  multiplex.py      # reti multiplex: layer multipli sugli stessi nodi (per anno,
                  # per interaction_type o grafi sovrapposti con add_layer),
                  # selezione layer e flatten con strategie di merge stile Gephi
  data_table.py     # tabella dati stile "Data Laboratory" di Gephi: nodi/edge come
                  # DataFrame con colonne calcolate (degree, degree_pesato,
                  # entropia, comunita), ordinamento, selezione per condizione,
                  # cancellazione vera dei nodi dal grafo (negativo di build_subgraph)
  comparison.py     # confronto tra due reti/snapshot: nodi/edge entrati-usciti,
                  # delta di degree, delta metriche di sintesi, tabella per nodo
  coarsening.py     # fusione nodi (coarse-graining) per tipo/categoria/comunità
  temporal.py       # split per anno (snapshot/cumulativo), metriche nel tempo
  animation.py      # GIF dell'evoluzione temporale: un frame per anno, layout
                  # fisso sull'unione degli anni, nodi inattivi come "fantasmi",
                  # frame PNG opzionali per montaggi video
  styling.py        # colore (hue categoria + sfumatura per variabile continua,
                  # stessa hue a luminosità variabile), dimensione, forma
  layout.py         # calcolo posizioni (spring / kamada-kawai / ForceAtlas2 se
                  # disponibile) con cache in memoria dei layout calcolati
  export.py         # GEXF (Gephi), GraphML+CSV (Cytoscape), PNG, HTML interattivo
                  # (pyvis), Excel Nodi+Edges con colonne originali (valori multipli
                  # separati da ', ') + build_interactive_html: finestra di lavoro
                  # vis.js embeddata nella GUI (fisica live o posizioni fisse)
  dedup.py          # pulizia nomi sporchi: label simili (probabili duplicati),
                  # fusione nodi con eredità attributi ', ', rinomina ID/label
  link_prediction.py # metodi classici (Adamic-Adar, Jaccard, ...) + validazione
                  # hold-out temporale (train anni passati, test anno successivo)
  link_prediction_ml.py # ML supervisionato sulle transizioni anno→anno (logistica
                  # sklearn o interna numpy; feature = punteggi classici + degree)
  lifecycle.py      # lettura fase ciclo di vita IPARL da metrics_over_time,
                  # criteri espliciti e soglie regolabili
  materiality.py    # matrice di materialità X × Y × dimensione con quadranti,
                  # attributi a scelta (proxy finché mancano dati di rilevanza)
  impact.py         # calcolatore EVPA readonly (deadweight/attribution/
                  # displacement/drop-off da stime utente)
  simulation.py     # framework a classi di nodi con regole (truth-table
                  # preferenze + accettazione + migrazione -> MultiGraph a layer)
                  # + Granovetter (cascate a soglia) + Ising (Glauber) + Schelling
  llm_agents.py     # nodi agentici: provider intercambiabili (Ollama locale /
                  # Claude API / Gemini API), ask_json robusto, accettazione
                  # LLM per la simulazione con budget/cache/log dei motivi
  report.py         # compila templates/report_template.html con i risultati (incluse
                  # betweenness, clustering, per-comunità, robustezza e GIF animata)
  persistence.py    # salva/riprendi il progetto (.nap): pipeline completa + stato
                  # GUI, per lavorare in più riprese (payload pickle: aprire solo
                  # file fidati)
  pipeline.py       # classe NetworkPipeline che orchestra tutto: unico punto d'ingresso

templates/
  report_template.html   # scheletro report con placeholder auto-compilati (KPI,
                         # tabelle, immagini base64), sezioni organizzate secondo le
                         # tre dimensioni SNA (Connectivity / Health / Results)

gui_app.py          # GUI Streamlit (streamlit run gui_app.py), layer sottile sopra
                    # la pipeline: dati, reti derivate (proiezioni anche filtrate,
                    # coarse-graining), multiplex (layer + composizione), filtri/
                    # ego-network (con scelta del grado di vicinanza), tabella dati
                    # (ordina/seleziona per condizione/elimina nodi), metriche (con
                    # broker, clustering, per-comunità, robustezza), analisi temporale
                    # (proiezione per anno, confronto tra snapshot, animazione GIF),
                    # styling + finestra interattiva vis.js (fisica live, drag,
                    # pannello regolazioni), export, report
```

## Cose da sapere

- Le analisi temporali vanno fatte sul grafo bipartito (che porta l'anno
  sull'edge), non sulle proiezioni; per una proiezione annuale usare
  `projections.project_by_year` — documentato nel README.
- "Sostegno non specificato" è escluso di default da `build_bipartite()`;
  il nodo radice (`config.root_label`) è usato solo da `pipeline.ego_on_root()`.

# TODO / possibili estensioni (per Claude Code)

Rimasti dal primo giro:

- Eventuale integrazione readonly delle metriche di impatto (deadweight,
  attribution, displacement, drop-off dal framework EVPA descritto nel brief
  teorico, §1.5) come modulo separato, se si vorrà estendere oltre la sola
  analisi strutturale.

Nuovi (richiesti dall'utente):

- **Link prediction agentica**: valutare coppie candidate con un LLM
  (llm_agents.py ha già provider e ask_json) — ATTENZIONE privacy: le
  coppie reali portano i nomi degli enti, usare SOLO Ollama locale.
- **Regole di simulazione apprese con ML**: stimare la truth-table delle
  preferenze dai dati osservati (es. da Interaction_Type per classe).
- **Provider "pupau"**: da aggiungere a llm_agents (una classe con .chat)
  quando l'utente avrà le istruzioni di configurazione del servizio.

Derivati dal riferimento teorico di progetto:

- **Dati di rilevanza per la materialità** (§1.9): la matrice c'è
  (materiality.py) ma usa attributi proxy scelti dall'utente; quando
  esisteranno colonne di rilevanza dedicate negli Excel, passarle come
  x_attr/y_attr (nessuna modifica al codice necessaria).
- **Visualizzazione avanzata**: layout Yifan Hu (non esiste in
  vis.js/networkx — oggi si passa da Gephi via GEXF), vista 3D
  (richiederebbe three.js/ForceGraph3D), eventuale packaging desktop
  (Electron/pywebview) se la GUI browser non bastasse più.

Fatti (spostati in "Concetti chiave" del README): proiezione per anno, cache
layout, confronto tra snapshot, animazione dell'evoluzione, betweenness,
clustering, densità/entropia per comunità, robustezza/dipendenza, proiezione
filtrata (rete delle fondazioni), tabella dati stile Data Laboratory,
reti multiplex (layer + merge stile Gephi), scelta del grado di vicinanza
nell'ego-network dalla GUI, persistenza del progetto (.nap, salva/riprendi
tra sessioni), report HTML con le nuove metriche e la GIF animata,
export Excel con colonne originali (eredità ', '), pulizia nomi sporchi
(dedup), finestra interattiva vis.js, link prediction classica con hold-out
temporale, lettura ciclo di vita, metriche multiplex cross-layer, matrice
di materialità, calcolatore EVPA (con form GUI e sezione report), framework
di simulazione a classi di nodi con Granovetter, Ising e Schelling (tab GUI),
link prediction ML supervisionata, stile degli edge per layer/attributo
propagato a tutti i renderer.
