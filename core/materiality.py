"""
materiality.py
Matrice di materialità (brief §1.9): rilevanza per gli stakeholder (X) ×
rilevanza per l'organizzazione (Y) × contributo all'impatto (Z = dimensione
del punto), per scegliere quali nodi/categorie enfatizzare nel report.

I dati Excel attuali NON contengono colonne di "rilevanza": il modulo è
quindi GENERICO — si sceglie quali attributi (originali o calcolati dalla
pipeline: degree, degree_pesato, betweenness, entropia, importo, ...) usare
come X, Y e Z. Quando/se arriveranno colonne di rilevanza dedicate,
basterà passarle come x_attr/y_attr senza toccare il codice.

- `materiality_table(G, x_attr, y_attr, size_attr, group_by)` — una riga per
  nodo o per gruppo (media/somma degli attributi), con il quadrante di
  appartenenza rispetto alle mediane.
- `plot_materiality(rows, path)` — scatter con le linee dei quadranti.
"""

from __future__ import annotations

import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _numeric(G: nx.Graph, n, attr) -> float | None:
    try:
        return float(G.nodes[n].get(attr))
    except (TypeError, ValueError):
        return None


def materiality_table(G: nx.Graph, x_attr: str, y_attr: str,
                       size_attr: str | None = None, group_by: str | None = None,
                       agg: str = "mean") -> list[dict]:
    """
    Righe {nome, x, y, size, quadrante}. Con group_by (es. 'category') una
    riga per gruppo (agg='mean' o 'sum' degli attributi dei membri);
    senza, una riga per nodo. I nodi senza valori numerici sono esclusi.
    Quadranti (rispetto alle mediane di X e Y):
      'chiave' (X alta, Y alta), 'stakeholder' (X alta), 'interno' (Y alta),
      'marginale' (entrambe basse).
    """
    points = []
    for n in G.nodes():
        x, y = _numeric(G, n, x_attr), _numeric(G, n, y_attr)
        if x is None or y is None:
            continue
        z = _numeric(G, n, size_attr) if size_attr else 1.0
        key = str(G.nodes[n].get(group_by)) if group_by else str(G.nodes[n].get("label", n))
        points.append((key, x, y, z if z is not None else 1.0))
    if not points:
        return []

    if group_by:
        grouped: dict = {}
        for key, x, y, z in points:
            grouped.setdefault(key, []).append((x, y, z))
        combine = (lambda vals: sum(vals) / len(vals)) if agg == "mean" else sum
        points = [(k, combine([p[0] for p in v]), combine([p[1] for p in v]),
                    combine([p[2] for p in v])) for k, v in grouped.items()]

    xs = sorted(p[1] for p in points)
    ys = sorted(p[2] for p in points)
    med_x, med_y = xs[len(xs) // 2], ys[len(ys) // 2]

    def quadrante(x, y):
        if x >= med_x and y >= med_y:
            return "chiave"
        if x >= med_x:
            return "stakeholder"
        if y >= med_y:
            return "interno"
        return "marginale"

    rows = [{"nome": k, "x": round(x, 4), "y": round(y, 4), "size": round(z, 4),
              "quadrante": quadrante(x, y)} for k, x, y, z in points]
    return sorted(rows, key=lambda r: (-r["x"] - r["y"]))


def plot_materiality(rows: list[dict], path: str, x_label: str = "Rilevanza stakeholder (X)",
                      y_label: str = "Rilevanza organizzazione (Y)",
                      title: str = "Matrice di materialità", annotate: int = 15) -> str:
    """Scatter con linee dei quadranti alle mediane; annota i primi
    `annotate` punti (già ordinati per rilevanza combinata)."""
    if not rows:
        raise ValueError("Nessun punto da disegnare (attributi non numerici?).")
    xs = [r["x"] for r in rows]
    ys = [r["y"] for r in rows]
    smax = max(r["size"] for r in rows) or 1
    sizes = [40 + 260 * r["size"] / smax for r in rows]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(xs, ys, s=sizes, alpha=0.6, edgecolors="white", linewidths=0.5)
    med_x = sorted(xs)[len(xs) // 2]
    med_y = sorted(ys)[len(ys) // 2]
    ax.axvline(med_x, color="#888", ls="--", lw=1)
    ax.axhline(med_y, color="#888", ls="--", lw=1)
    for r in rows[:annotate]:
        ax.annotate(str(r["nome"])[:28], (r["x"], r["y"]), fontsize=7,
                     xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel(x_label); ax.set_ylabel(y_label); ax.set_title(title)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
