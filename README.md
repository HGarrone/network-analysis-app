# Network Analysis — Enti e Progetti

Pipeline Python modulare per l'analisi della rete Enti↔Progetti, pensata per
essere estesa con Claude Code. Ogni funzionalità è una funzione/classe pura
in `core/`, richiamabile sia da script/notebook sia dalla GUI Streamlit
(`gui_app.py`).

## Installazione

```bash
pip install -r requirements.txt
```

## Uso rapido (script)

```python
from core.pipeline import NetworkPipeline

p = NetworkPipeline("nodi.xlsx", "edges.xlsx")
p.load()
G = p.build_bipartite(exclude_default=True)  # esclude "Sostegno non specificato"

ente_ente = p.get_projection("ente", weight_mode="count")
metrics = p.compute_metrics(ente_ente)
p.style(ente_ente, color_by="category", shape_by="type")
paths = p.export(ente_ente, out_dir="output", basename="ente_ente")
p.build_report("output/report.html", G=ente_ente, metrics=metrics,
                network_png_path=paths["png"])
```

## Uso GUI

```bash
streamlit run gui_app.py
```
Carica i due file Excel (nodi/edges) dalla barra laterale, poi naviga le tab:
Reti derivate → Multiplex → Filtri/Ego-network → Tabella dati → Metriche →
Analisi temporale → Styling → Export & Report.

## Struttura del progetto

La struttura dettagliata dei moduli (e la lista dei TODO / estensioni
possibili) è in `Struttura_e_todo.md`.

## Concetti chiave implementati

- **Ego-network generalizzata** (`ego.py`): il seme può essere un nodo singolo
  o un filtro su attributo (es. `{"type": "Fondazione"}`).
  `pipeline.ego_on_root()` è la scorciatoia per un nodo radice fisso
  (`config.root_label`), reintrodotto anche se escluso dalle altre analisi.
- **Filtri doppi** (`filters.py`): `build_subgraph` è un filtro di
  *selezione* (costruisce una rete nuova, riusabile per qualunque metrica);
  `visualization_mask` è un filtro di *visualizzazione* (nasconde/mostra
  senza toccare il grafo, per esplorazione rapida in GUI).
- **Colore multi-livello** (`styling.py`): hue = categoria, luminosità/shade =
  variabile continua (importo, degree, anno...), così le due informazioni
  sono sovrapponibili senza perdere la leggibilità della categoria.
- **Densità**: implementate entrambe le definizioni — `densita_links_su_nodi`
  (|E|/|V|, quella usata nel brief) e `densita_standard_0_1` (networkx, per
  confronto/normalizzazione).
- **Entropia di vicinato** (`metrics.neighbor_entropy`): entropia di Shannon
  della distribuzione di un attributo categoriale (default `category`) tra i
  vicini diretti di ogni nodo; normalizzata in [0,1] per confrontabilità.
- **Tabella dati stile "Data Laboratory" di Gephi** (`data_table.py`):
  `nodes_table` / `edges_table` restituiscono la rete attiva come DataFrame
  pandas, con le colonne calcolate a runtime (`degree`, `degree_pesato`,
  `entropia`, `comunita`) aggiunte come veri attributi dei nodi (quindi
  ordinabili, filtrabili ed esportabili). `select_ids_by_conditions` seleziona
  righe per condizione (es. `("degree", "==", 0)`); `remove_nodes` /
  `remove_by_conditions` eliminano i nodi selezionati (e gli edge incidenti)
  costruendo un **nuovo grafo** — è il negativo di `filters.build_subgraph`
  (rimuovi anziché tieni), da non confondere con i filtri di visualizzazione.
  Uso tipico: ripulire la rete dai nodi isolati dopo un filtro o una
  proiezione:

  ```python
  clean, removed = p.remove_by_conditions(G, [("degree", "==", 0)])
  ```

- **Proiezione per anno** (`projections.project_by_year`): divide prima il
  bipartito per anno (snapshot o cumulativo), poi proietta ogni sottografo
  annuale sul lato scelto — ritorna `{anno: grafo_proiettato}`. Dalla GUI:
  tab Analisi temporale → "Proiezione per anno", con possibilità di attivare
  la proiezione di un anno come rete corrente.
- **Cache dei layout** (`layout.py`): le posizioni calcolate vengono
  riutilizzate se la rete (nodi+edge+pesi) e i parametri non cambiano —
  utile perché spring_layout è lento oltre qualche migliaio di nodi e la GUI
  ricalcolava a ogni anteprima/export. Trasparente (qualunque modifica al
  grafo forza il ricalcolo), disattivabile con `use_cache=False`,
  svuotabile con `layout.clear_cache()`.
- **Confronto tra snapshot/reti** (`comparison.py`): `compare_graphs(G1, G2)`
  ritorna nodi/edge entrati-usciti, differenza di degree (semplice e pesato)
  per i nodi comuni e delta delle metriche di sintesi; `compare_years` è la
  scorciatoia per confrontare due anni del bipartito; `delta_table` produce
  il dettaglio per nodo come DataFrame ordinabile. Dalla GUI: tab Analisi
  temporale → "Confronto tra due snapshot".
- **Animazione dell'evoluzione temporale** (`animation.py`): GIF con un
  frame per anno e **layout fisso** calcolato sull'unione di tutti gli anni
  (i nodi non saltano tra i frame: si vede la rete accendersi e addensarsi).
  I nodi non ancora attivi restano visibili come "fantasmi" grigi
  (disattivabile), colore per attributo categoriale costante su tutti i
  frame, opzionalmente salva anche i singoli frame PNG (`frames_dir`) per
  montaggi video. `pipeline.animate(path, mode, on)` anima il bipartito o
  la proiezione per anno; `animate_graphs({anno: grafo}, path)` anima
  qualunque sequenza già calcolata. Dalla GUI: tab Analisi temporale →
  "Animazione dell'evoluzione nel tempo" (anteprima + download).
- **Betweenness, clustering e metriche per comunità** (`metrics.py`):
  `betweenness_centrality` identifica i broker/ponti strutturali tra
  cluster (anche colonna calcolata nella tabella dati); `clustering_report`
  (clustering medio + transitività) per leggere la fase del ciclo di vita
  del network (sensato sulle proiezioni, non sul bipartito che è privo di
  triangoli); `per_community_report` calcola densità ed entropia ristrette
  a ogni comunità. Tutto incluso in `full_metrics_report` e nella tab
  Metriche della GUI.
- **Robustezza / dipendenza** (`robustness.py`, dimensione Health):
  `key_node_dependency` misura l'effetto della rimozione di un singolo nodo
  centrale alla volta (componenti, frammentazione); `attack_simulation`
  rimuove progressivamente i nodi più centrali (degree / degree pesato /
  betweenness / random come baseline) e traccia la traiettoria della
  frammentazione — il confronto mirato-vs-random è la misura classica di
  ridondanza. Dalla GUI: tab Metriche → espansore "Robustezza / dipendenza".
- **Densità/entropia a granularità multiple** (`granular.py` + tab Metriche
  → "🧭 Granularità multiple"): un motore unico calcola il set di metriche
  di gruppo — densità (entrambe le definizioni), entropia di vicinato,
  **entropia di composizione** (diversità settoriale interna al gruppo),
  **indice E-I di Krackhardt** (omofilia/eterofilia dei legami),
  clustering, **centralizzazione di Freeman**, **Gini del degree**
  (dipendenza da hub), componenti/isolati — alle granularità scelte e
  componibili: tutta la rete, per comunità, per valore di un attributo,
  per anno (snapshot/cumulativo), anno×attributo, anno×comunità, più
  porzioni filtrate a piacere (criteri stile filters.py). Output: tabella
  lunga (una riga per gruppo) ed **export Excel** con foglio dati, fogli
  pivot per anno già pronti per i grafici e legenda delle metriche.
  Le metriche di gruppo derivano dalle dimensioni Connectivity/Health del
  riferimento teorico di social network analysis. Aggiungere una metrica =
  una entry in `group_metrics` + `METRICHE_LEGENDA`.
- **Nodi agentici** (`llm_agents.py` + tab Simulazione → "🤖 Nodi
  agentici"): le condizioni di accettazione della simulazione a regole
  possono essere decise da un modello AI, nodo per nodo, con **budget di
  chiamate**, **cache** delle situazioni identiche e **log dei motivi**.
  Provider intercambiabili (una classe ciascuno, stessa interfaccia
  `.chat`): **Ollama locale** (consigliato — nessun dato lascia la
  macchina; elenco filtrato ai modelli adatti: qwen3, deepseek-r1, gemma4,
  mistral, llama3.2), **Claude API** (haiku/sonnet, chiave da
  ANTHROPIC_API_KEY) e **Gemini API** (chiave da GEMINI_API_KEY). Le chiavi
  non vengono mai salvate nel progetto. Al modello va SOLO il contesto
  sintetico della simulazione (classi, contatori) — mai i dati reali;
  `ask_json` gestisce risposte con code fence e blocchi di ragionamento
  (deepseek-r1/qwen3). Aggiungere un provider = una classe nuova.
- **Stile degli edge per layer/attributo** (`styling.apply_edge_style`,
  integrato in `apply_style` con `edge_color_by`): colora gli edge per un
  attributo categoriale ('layer' del multiplex composto, 'interaction_type',
  'anno') con la stessa logica di palette dei nodi, e spessore per peso.
  Tutti i renderer (PNG, HTML pyvis, finestra interattiva, GEXF) leggono
  `viz_edge_color`/`viz_width`: un'impostazione aggiunta in styling.py si
  applica automaticamente ovunque. Funziona anche sui MultiGraph.
- **Link prediction ML** (`link_prediction_ml.py`, modulo separato dalla
  versione classica): regressione logistica sulle feature strutturali
  (i punteggi dei metodi classici + degree), allenata sulle transizioni
  anno→anno reali (positivi = coppie che si sono collegate, negativi
  campionati) e applicata all'ultima rete cumulativa con probabilità.
  Usa scikit-learn se installato, altrimenti un'implementazione interna in
  numpy (nessuna dipendenza obbligatoria). Nuove feature = una entry nel
  dict `FEATURES`. GUI: tab Link prediction → "ML supervisionato".
- **Link prediction** (`link_prediction.py` + tab "🔮 Link prediction"):
  suggerisce coppie non collegate ma strutturalmente vicine (potenziali
  collaborazioni) con i metodi classici — common neighbors, Jaccard,
  Adamic-Adar, resource allocation, preferential attachment — su candidati
  a distanza 2 (efficiente). Da usare sulle proiezioni. La validazione con
  **hold-out temporale** allena sulla rete cumulativa fino all'anno prima e
  misura la precision@k sui nuovi legami dell'anno di test. Un metodo nuovo
  = una entry nel dict `METHODS`.
- **Lettura del ciclo di vita** (`lifecycle.py`): propone la fase IPARL
  (Inception → Growth → Maturity → Transition) dagli output di
  `metrics_over_time`, con criteri espliciti e soglie regolabili
  (crescita nodi, delta densità/clustering); ogni proposta è motivata dai
  valori che l'hanno determinata. Nella GUI: tab Analisi temporale.
- **Metriche multiplex cross-layer** (`multiplex.py`): `multiplexity_report`
  (coppie collegate su più layer), `layer_overlap` (Jaccard tra layer),
  `intensity_levels` (livello cumulativo massimo per coppia dato l'ordine
  dei layer dal più debole al più forte, brief §1.1). Nella GUI: tab
  Multiplex → espansore "Metriche multiplex".
- **Matrice di materialità** (`materiality.py`): X × Y × dimensione con
  quadranti alle mediane (chiave/stakeholder/interno/marginale), per nodo o
  per gruppo. Generica: si scelgono gli attributi (anche calcolati) come
  proxy finché non esistono colonne di rilevanza dedicate — quando ci
  saranno, basterà passarle come x_attr/y_attr. GUI: tab Metriche.
- **Calcolatore EVPA readonly** (`impact.py`): impatto netto = outcome ×
  (1-deadweight) × (1-attribution) × (1-displacement), con drop-off annuo
  dal 2° anno; `impact_table` per più progetti. I 4 bias sono STIME fornite
  dall'utente (non calcolabili dai dati di rete): il modulo non inventa
  numeri. GUI: tab Export & Report → espansore "🎯 Impatto EVPA" (tabella
  editabile delle stime); il risultato entra nella sezione 8 del report HTML.
- **Framework di simulazione a classi di nodi** (`simulation.py`):
  `SimulationRules` = truth-table delle preferenze {(classe_proponente,
  classe_ricevente): [tipi di edge in ordine di tentativo]} + condizioni di
  accettazione per (classe, tipo, proponente) come callable sostituibili
  (in futuro: ML o agenti AI) + regola di migrazione quando nessun tipo è
  accettato. Il motore `simulate` produce un MultiGraph con `layer` = tipo
  di edge, analizzabile direttamente con multiplex.py. L'esempio A/B/C del
  brief è nel docstring. Inclusi i modelli classici: `granovetter_cascade`
  (soglie di adozione), `ising_dynamics` (Glauber, consenso/polarizzazione)
  e `schelling_segregation` (migrazione su nodi vuoti per intolleranza,
  con indice di segregazione nel tempo). GUI: tab "🧪 Simulazione"
  (Granovetter/Ising/Schelling sulla rete corrente + framework a regole con
  la truth-table A/B/C precompilata e modificabile; la rete simulata si può
  attivare come rete corrente).
- **Export Excel con le colonne originali** (`export.export_excel`, incluso
  in `export_all`): qualunque rete (proiettata, filtrata, coarse-grained,
  pulita) esce come un unico `.xlsx` con fogli **Nodi** ed **Edges**, con le
  intestazioni originali dei file di partenza (ID, Label, Type, Category,
  Ambito/Ruolo, ..., Interaction_Type, Importo) più le colonne calcolate
  (degree, comunita, ...). Se un nodo/edge eredita valori diversi (fusioni,
  accorpamenti), li mantiene **tutti separati da ", "**.
- **Pulizia dei nodi con nomi sporchi** (`dedup.py` + tab "🧹 Pulizia
  nodi"): all'import la GUI segnala automaticamente i gruppi di label molto
  simili (normalizzazione maiuscole/accenti/punteggiatura + similarità di
  sequenza e di parole, soglia regolabile) che probabilmente sono lo stesso
  ente scritto in modi diversi. Dalla tab si uniscono i duplicati
  (`merge_nodes`: edge riattaccati con pesi sommati e records concatenati,
  attributi diversi ereditati con ", ") e si correggono ID/label dei
  singoli nodi (`rename_node`). La pulizia fatta sul bipartito si propaga
  alle proiezioni calcolate dopo. Il coarse-graining eredita anch'esso gli
  attributi originali dei membri con la regola ", " (`membri_labels`
  conserva le label originali).
- **Finestra di lavoro interattiva** (`export.build_interactive_html` +
  tab Styling/Visualizzazione della GUI): la rete corrente incorporata
  nella GUI come vista vis.js con zoom, drag dei nodi, tooltip e pannello
  con gli slider della fisica (stile Gephi). Ottimizzazione del layout:
  fisica live **ForceAtlas2-based / Barnes-Hut / Repulsione**, oppure
  posizioni precalcolate (spring / kamada_kawai / fa2 se installato) con
  fisica spenta ma nodi comunque trascinabili. La vista riflette sempre la
  rete corrente, quindi filtri/fusioni/cancellazioni fatte nelle altre tab
  si vedono qui. Yifan Hu e la vista 3D non esistono in vis.js/networkx:
  per quelli esportare il GEXF e rifinire in Gephi.
- **Persistenza del progetto** (`persistence.py`): salva l'intero stato in
  un file `.nap` (zip con manifest leggibile + payload pickle) e riprendilo
  in una sessione successiva: pipeline completa (DataFrame, bipartito, reti
  derivate, multiplex, config) e stato della GUI (rete corrente, metriche,
  tabelle, condizioni, confronti). Dalla GUI: barra laterale → "Progetto
  (salva / riprendi)". Non vengono salvati bottoni/checkbox e percorsi di
  file temporanei (anteprime/GIF si rigenerano in un click). ATTENZIONE:
  il payload è pickle — aprire solo file di progetto fidati.
- **Report con le metriche complete e la GIF**: il template ora ha sezioni
  per broker (betweenness), clustering/transitività, metriche per comunità,
  robustezza/dipendenza (nuova sezione Health) e l'animazione dell'evoluzione
  (GIF base64 embeddata, resta animata nel file HTML). La GUI include
  automaticamente nel report tutto ciò che è già stato calcolato nelle
  altre tab.
- **Reti multiplex** (`multiplex.py`): più tipi di legame (layer) tra gli
  stessi nodi, rappresentate come `nx.MultiGraph` con attributo `layer` su
  ogni edge e `layers` su ogni nodo. Tre modi di costruire i layer:
  `build_multiplex(G, layer_by="anno"|"interaction_type")` divide gli edge
  per attributo (espandendo le multi-relazioni `records` del bipartito, così
  Partner/Capofila/Cofinanziatore finiscono ciascuno nel proprio layer);
  `add_layer(M, G_layer, nome)` sovrappone un intero grafo come layer (es.
  la proiezione ente-ente sopra la rete totale); i due si combinano.
  `flatten(M, layers, strategy, merge_scope)` seleziona i layer da
  sovrapporre e risolve gli edge paralleli con le strategie di Gephi
  (`sum`, `mean`, `max`, `min`, `count`, `first`, `last`) e tre ambiti:
  unisci tutto / non unire tra layer diversi / non unire mai. Dalla GUI:
  tab "🧅 Multiplex" (crea da attributo, aggiungi la rete corrente come
  layer, componi e attiva la rete risultante).
- **Ego-network con scelta del grado**: `ego_network_by_degree` ritorna la
  sotto-rete per OGNI grado di distanza fino a `max_hops`; nella GUI, dopo
  il calcolo, una tabella riassume i gradi (nodi interni/esterni, edge) e
  si sceglie quale grado attivare come rete corrente.
- **Proiezione filtrata / rete delle fondazioni** (`projections.project`
  con `node_filter`): proietta solo i nodi che soddisfano un criterio (es.
  `{"type": "Fondazione"}`) — due fondazioni restano collegate dal progetto
  condiviso anche se vi partecipano altri enti, ma gli altri enti non
  entrano nella rete. Diverso (e più corretto per la "rete delle
  fondazioni") dal filtrare dopo la proiezione completa. Disponibile anche
  in `project_by_year` e dalla GUI (tab Reti derivate → filtro opzionale).
- **Import/export interoperabile con Gephi/Cytoscape**:
  - **Gephi** → GEXF (formato nativo, preferito).
  - **Cytoscape** → sia GraphML sia coppia di CSV (node table + edge table,
    più flessibile per definire lo stile direttamente nell'interfaccia
    di Cytoscape). Vedi `export.export_cytoscape_tables`.
  - `data_io.import_gexf` / `import_graphml` per riprendere un lavoro fatto a
    mano in quei tool.

## Note metodologiche

- L'attributo temporale (`anno`) vive sugli **edge del grafo bipartito**, non
  sulle proiezioni Ente-Ente/Progetto-Progetto (che non hanno un anno
  univoco per edge, essendo derivate). Le analisi temporali vanno quindi
  fatte su `pipeline.G_bipartite`; per una proiezione annuale usare
  `projections.project_by_year` (vedi Concetti chiave).
- "Sostegno non specificato" è escluso di default da `build_bipartite()`
  (hub artificiale che distorce densità e centralità). Se i dati sono
  l'ego-network di un nodo centrale, conviene escludere anche quello e
  usarlo come `config.root_label` per `pipeline.ego_on_root()`.

I TODO e le possibili estensioni sono elencati in `Struttura_e_todo.md`.
