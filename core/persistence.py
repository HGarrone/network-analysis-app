"""
persistence.py
Salvataggio e caricamento dello STATO DEL PROGETTO, per lavorare in più
riprese: pipeline completa (DataFrame nodi/edges, grafo bipartito, reti
derivate in cache, multiplex, config) + stato della GUI (rete corrente,
metriche calcolate, tabelle, condizioni, risultati di confronto, ...).

Formato file: un archivio zip (estensione consigliata .nap, "network
analysis project") contenente:
- manifest.json  — leggibile: versione formato, nome, data, chiavi salvate
- state.pkl      — pickle di {"pipeline": NetworkPipeline, "session": dict}

NOTA SICUREZZA: il payload è pickle (necessario per salvare fedelmente
grafi networkx, DataFrame e oggetti Python senza perdite). Il pickle può
eseguire codice al caricamento: aprire SOLO file di progetto creati da sé
o da fonti fidate.

Cosa NON viene salvato dello stato GUI (per costruzione):
- valori booleani (bottoni e checkbox: transienti — un bottone "premuto"
  salvato scatterebbe di nuovo al caricamento);
- chiavi che puntano a file temporanei (anteprime PNG/GIF, export): i
  percorsi non sopravvivono tra sessioni — si rigenerano in un click;
- oggetti non serializzabili (es. file caricati via uploader).
"""

from __future__ import annotations

import datetime
import json
import pickle
import zipfile

FORMAT_VERSION = 1
DEFAULT_EXTENSION = ".nap"

# chiavi di sessione da non salvare mai: oggetti gestiti a parte o percorsi temporanei
EXCLUDED_SESSION_KEYS = {"pipeline", "anim_gif", "preview_png", "export_paths",
                          "project_file", "interactive_html", "mat_png",
                          "llm_api_key"}  # mai salvare chiavi API nel progetto


def collect_session(session_state) -> dict:
    """
    Estrae dallo st.session_state (o da qualunque mapping) il sottoinsieme
    salvabile: esclude le chiavi in EXCLUDED_SESSION_KEYS, i booleani
    (bottoni/checkbox) e tutto ciò che non è picklabile.
    """
    out = {}
    for k in list(session_state.keys()):
        if k in EXCLUDED_SESSION_KEYS:
            continue
        v = session_state[k]
        if isinstance(v, bool):
            continue
        try:
            pickle.dumps(v)
        except Exception:
            continue
        out[k] = v
    return out


def save_project(path: str, pipeline=None, session: dict | None = None,
                  nome: str = "") -> str:
    """
    Salva pipeline + stato di sessione nel file di progetto.
    `session` è un dict già filtrato (vedi collect_session).
    """
    session = session or {}
    manifest = {
        "format_version": FORMAT_VERSION,
        "nome": nome,
        "salvato_il": datetime.datetime.now().isoformat(timespec="seconds"),
        "ha_pipeline": pipeline is not None,
        "chiavi_sessione": sorted(session.keys()),
    }
    payload = {"pipeline": pipeline, "session": session}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        z.writestr("state.pkl", pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    return path


def read_manifest(path: str) -> dict:
    """Legge il solo manifest (senza deserializzare il pickle): utile per
    mostrare nome/data prima di decidere se caricare."""
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("manifest.json").decode("utf-8"))


def load_project(path: str) -> dict:
    """
    Carica il file di progetto. Ritorna
    {"manifest": dict, "pipeline": NetworkPipeline|None, "session": dict}.
    ATTENZIONE: deserializza pickle — aprire solo file fidati (vedi sopra).
    """
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        if manifest.get("format_version", 0) > FORMAT_VERSION:
            raise ValueError(
                f"File di progetto in formato {manifest.get('format_version')} "
                f"più recente di quello supportato ({FORMAT_VERSION}): aggiorna il programma.")
        payload = pickle.loads(z.read("state.pkl"))
    return {"manifest": manifest,
            "pipeline": payload.get("pipeline"),
            "session": payload.get("session", {})}
