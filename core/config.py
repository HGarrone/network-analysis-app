"""
config.py
Configurazione centrale: nomi colonne dei file sorgente, formula del peso degli edge,
palette colori di base. Modificare qui se cambiano i nomi delle colonne nei file Excel,
senza toccare il resto della pipeline.
"""

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Nomi colonne — file NODI
# ---------------------------------------------------------------------------
NODE_COLS = {
    "id": "ID",
    "label": "Label",
    "type": "Type",
    "category": "Category",
    "ambito": "Ambito/Ruolo",
    "sotto_ambito": "Sotto-ambito",
    "dettaglio": "Dettaglio",
    "anno": "Anno",  # stringa tipo "2024, 2025"
}

# ---------------------------------------------------------------------------
# Nomi colonne — file EDGES
# ---------------------------------------------------------------------------
EDGE_COLS = {
    "anno": "Anno",              # intero singolo, es. 2024
    "source": "Source",          # ID ente
    "label_ente": "Label ente",
    "dettagli_ente": "Dettagli Nome ente",
    "type_ente": "Type ente",
    "interaction_type": "Interaction_Type",  # Partner / Ente capofila / Cofinanziatore
    "target": "Target",          # ID progetto
    "label_progetto": "Label Progetto",
    "dettaglio_progetto": "Dettaglio Progetto",
    "category_progetto": "Category Progetto",
    "ambito_progetto": "Ambito Progetto",
    "sotto_ambito_progetto": "Sotto-ambito Progetto",
    "importo": "Importo",
    "forza_contributo": "Forza contributo",  # peso, se già calcolato nel file
}

INTERACTION_TYPES = {
    "capofila": "Ente capofila",
    "partner": "Partner",
    "cofinanziatore": "Cofinanziatore",
}

# Nodi da rimuovere di default nelle analisi strutturali: "Sostegno non
# specificato" è un hub artificiale che genera falsi positivi nelle proiezioni.
DEFAULT_EXCLUDED_NODE_LABELS = ["Sostegno non specificato"]
DEFAULT_ROOT_LABEL = ""  # label del nodo centrale per ego_on_root() — da impostare in base ai dati


def compute_weight(interaction_type: str, importo) -> float:
    """
    Riproduce la formula 'Forza contributo' descritta dall'utente:
      - Cofinanziatore -> 10 + log(importo)/7.22 * 100
      - Partner         -> 40
      - Ente capofila   -> 100
    Se il peso è già presente nel file edges, preferire sempre quella colonna:
    questa funzione serve per ricalcolare/validare o per dati mancanti.
    """
    if interaction_type is None:
        return 0.0
    it = str(interaction_type).strip().lower()
    if it == INTERACTION_TYPES["capofila"].lower():
        return 100.0
    if it == INTERACTION_TYPES["partner"].lower():
        return 40.0
    if it == INTERACTION_TYPES["cofinanziatore"].lower():
        try:
            importo = float(importo)
        except (TypeError, ValueError):
            return float("nan")
        if importo <= 0:
            return float("nan")
        return 10.0 + math.log(importo) / 7.22 * 100.0
    return float("nan")


# ---------------------------------------------------------------------------
# Palette di base per categorie (hue di partenza). Le sotto-categorie ottengono
# sfumature (variazione di luminosità/saturazione) della stessa hue: vedi styling.py
# ---------------------------------------------------------------------------
BASE_HUE_PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
]


@dataclass
class PipelineConfig:
    node_cols: dict = field(default_factory=lambda: dict(NODE_COLS))
    edge_cols: dict = field(default_factory=lambda: dict(EDGE_COLS))
    excluded_node_labels: list = field(default_factory=lambda: list(DEFAULT_EXCLUDED_NODE_LABELS))
    root_label: str = DEFAULT_ROOT_LABEL
