"""
impact.py
Calcolatore READONLY delle metriche di impatto del framework EVPA /
Impronta Etica (brief §1.5): catena Input → Attività → Output → Outcome →
Impatto, dove l'impatto netto sottrae i 4 bias:

- deadweight:   quota di cambiamento che sarebbe avvenuta comunque
- attribution:  quota di merito di attori esterni
- displacement: quota di problema spostato altrove anziché risolto
- drop_off:     decadimento annuo dell'effetto (applicato dal 2° anno)

I 4 bias NON sono calcolabili dai dati di rete: sono STIME fornite
dall'utente (frazioni in [0,1], es. da interviste/valutazioni). Il modulo
è un'utilità di calcolo trasparente per affiancare al report la lettura
di impatto quando quelle stime esistono — non inventa numeri.

- `net_impact(...)` — impatto netto di un singolo outcome.
- `impact_table(rows)` — tabella per più progetti/outcome con totali.
"""

from __future__ import annotations


def _check_fraction(name: str, value: float):
    if not 0 <= value <= 1:
        raise ValueError(f"{name} deve essere una frazione in [0,1], non {value}.")


def net_impact(outcome: float, deadweight: float = 0.0, attribution: float = 0.0,
                displacement: float = 0.0, drop_off: float = 0.0, years: int = 1) -> dict:
    """
    Impatto netto EVPA di un outcome lordo:
      netto_anno1 = outcome × (1-deadweight) × (1-attribution) × (1-displacement)
      anno k>1:    netto_anno1 × (1-drop_off)^(k-1)
      totale su `years` anni = somma dei contributi annui.
    Ritorna {netto_anno1, totale, per_anno, parametri}.
    """
    for name, v in [("deadweight", deadweight), ("attribution", attribution),
                     ("displacement", displacement), ("drop_off", drop_off)]:
        _check_fraction(name, v)
    if years < 1:
        raise ValueError("years deve essere >= 1.")
    anno1 = outcome * (1 - deadweight) * (1 - attribution) * (1 - displacement)
    per_anno = [round(anno1 * (1 - drop_off) ** k, 4) for k in range(years)]
    return {
        "outcome_lordo": outcome,
        "netto_anno1": round(anno1, 4),
        "per_anno": per_anno,
        "totale": round(sum(per_anno), 4),
        "parametri": {"deadweight": deadweight, "attribution": attribution,
                       "displacement": displacement, "drop_off": drop_off, "years": years},
    }


def impact_table(rows: list[dict]) -> dict:
    """
    Calcola l'impatto netto per una lista di progetti/outcome.
    Ogni riga: {"nome", "outcome", e opzionali deadweight/attribution/
    displacement/drop_off/years}. Ritorna {"righe": [...], "totale_lordo",
    "totale_netto"} — righe pronte per un DataFrame o per il report.
    """
    out_rows = []
    tot_lordo = tot_netto = 0.0
    for r in rows:
        res = net_impact(
            outcome=float(r["outcome"]),
            deadweight=float(r.get("deadweight", 0.0)),
            attribution=float(r.get("attribution", 0.0)),
            displacement=float(r.get("displacement", 0.0)),
            drop_off=float(r.get("drop_off", 0.0)),
            years=int(r.get("years", 1)),
        )
        out_rows.append({"nome": r.get("nome", ""), "outcome_lordo": res["outcome_lordo"],
                          "netto_anno1": res["netto_anno1"], "totale_netto": res["totale"],
                          **res["parametri"]})
        tot_lordo += res["outcome_lordo"]
        tot_netto += res["totale"]
    return {"righe": out_rows, "totale_lordo": round(tot_lordo, 4),
            "totale_netto": round(tot_netto, 4)}
