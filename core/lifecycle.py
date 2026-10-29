"""
lifecycle.py
Lettura della fase del ciclo di vita del network (framework IPARL, brief
§1.6): Inception → Growth → Maturity → Transition/Exit, a partire dalle
metriche per anno già calcolate da temporal.metrics_over_time.

I criteri sono ESPLICITI e regolabili (parametri con default documentati):
- Inception:   pochi anni osservati o rete piccola, clustering basso
- Growth:      nodi in forte crescita (>= soglia_crescita) e densità o
               clustering in aumento
- Maturity:    crescita dei nodi bassa (< soglia_stabilita) con densità/
               clustering stabili o in aumento (rete che consolida)
- Transition:  nodi o legami in calo (rete che si contrae)

La proposta è un'euristica di supporto alla lettura, non un verdetto:
ogni fase è accompagnata dai valori che l'hanno determinata.
"""

from __future__ import annotations

PHASES = ["Inception", "Growth", "Maturity", "Transition"]


def indicators_by_year(metrics_by_year: dict) -> list[dict]:
    """Estrae dagli output di metrics_over_time una riga per anno con gli
    indicatori usati per la lettura del ciclo di vita."""
    rows = []
    for y in sorted(metrics_by_year):
        r = metrics_by_year[y]
        rows.append({
            "anno": y,
            "n_nodi": r["densita"]["n_nodi"],
            "n_edge": r["densita"]["n_edge"],
            "densita_links_su_nodi": r["densita"]["densita_links_su_nodi"],
            "clustering_medio": (r.get("clustering") or {}).get("clustering_medio", 0.0),
            "entropia_media": r.get("entropia_media", 0.0),
            "n_comunita": r.get("n_comunita", 0),
        })
    for prev, cur in zip(rows, rows[1:]):
        cur["crescita_nodi"] = ((cur["n_nodi"] - prev["n_nodi"]) / prev["n_nodi"]
                                 if prev["n_nodi"] else 0.0)
        cur["delta_densita"] = cur["densita_links_su_nodi"] - prev["densita_links_su_nodi"]
        cur["delta_clustering"] = cur["clustering_medio"] - prev["clustering_medio"]
    return rows


def read_lifecycle(metrics_by_year: dict, soglia_crescita: float = 0.20,
                    soglia_stabilita: float = 0.05, min_anni: int = 3,
                    min_nodi: int = 30) -> dict:
    """
    Propone la fase del ciclo di vita dall'ULTIMO periodo osservato.
    Parametri (regolabili): soglia_crescita = crescita nodi/anno oltre cui
    si parla di Growth; soglia_stabilita = sotto questa crescita la rete è
    considerata stabile; min_anni/min_nodi = sotto queste soglie si resta
    in Inception. Ritorna {fase, motivazione, indicatori (per anno)}.
    """
    rows = indicators_by_year(metrics_by_year)
    if not rows:
        return {"fase": None, "motivazione": "Nessun dato temporale.", "indicatori": []}
    last = rows[-1]
    n_anni = len(rows)

    if n_anni < min_anni or last["n_nodi"] < min_nodi:
        fase, why = "Inception", (
            f"Osservati {n_anni} anni (min {min_anni}) e {last['n_nodi']} nodi "
            f"(min {min_nodi}): serie ancora corta o rete piccola.")
    elif last.get("crescita_nodi", 0) < 0 or last["n_edge"] < rows[-2]["n_edge"]:
        fase, why = "Transition", (
            f"Nell'ultimo anno i nodi variano del {last.get('crescita_nodi', 0):+.0%} "
            f"e i legami passano da {rows[-2]['n_edge']} a {last['n_edge']}: la rete si contrae.")
    elif last.get("crescita_nodi", 0) >= soglia_crescita and (
            last.get("delta_densita", 0) > 0 or last.get("delta_clustering", 0) > 0):
        fase, why = "Growth", (
            f"Crescita nodi {last['crescita_nodi']:+.0%} (soglia {soglia_crescita:.0%}) "
            f"con densità {last.get('delta_densita', 0):+.3f} e clustering "
            f"{last.get('delta_clustering', 0):+.3f}: la rete cresce e si connette.")
    elif abs(last.get("crescita_nodi", 0)) < soglia_stabilita and (
            last.get("delta_densita", 0) >= 0 or last.get("delta_clustering", 0) >= 0):
        fase, why = "Maturity", (
            f"Crescita nodi {last.get('crescita_nodi', 0):+.0%} sotto la soglia di "
            f"stabilità ({soglia_stabilita:.0%}) con densità/clustering non in calo: "
            "la rete consolida le relazioni esistenti.")
    else:
        fase, why = "Growth", (
            f"Crescita nodi {last.get('crescita_nodi', 0):+.0%} intermedia: "
            "rete in espansione moderata (tra Growth e Maturity).")

    return {"fase": fase, "motivazione": why, "indicatori": rows,
            "parametri": {"soglia_crescita": soglia_crescita,
                           "soglia_stabilita": soglia_stabilita,
                           "min_anni": min_anni, "min_nodi": min_nodi}}
