"""
report.py
Compila il template scheletro (templates/report_template.html) con i
risultati prodotti dalla pipeline, producendo un report HTML autosufficiente
(le immagini vengono embeddate in base64 così il file rimane singolo e
condivisibile).
"""

from __future__ import annotations

import base64
import datetime
import os

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")


def _img_to_base64_html(path: str, css_class: str = "network-viz",
                         mime: str = "image/png") -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f'<img class="{css_class}" src="data:{mime};base64,{b64}">'


def _df_to_html_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    return df.head(max_rows).to_html(index=False, border=0)


def _degree_table_html(degree_stats: dict, node_labels: dict, top_n: int = 15) -> str:
    per_nodo = degree_stats.get("per_nodo", {})
    rows = sorted(per_nodo.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    df = pd.DataFrame(
        [{"Nodo": node_labels.get(n, n), "Degree": d} for n, d in rows]
    )
    return _df_to_html_table(df)


def _entropy_table_html(entropy_per_node: dict, node_labels: dict, top_n: int = 10) -> str:
    items = sorted(entropy_per_node.items(), key=lambda kv: kv[1], reverse=True)
    top = items[:top_n]
    bottom = items[-top_n:]
    df = pd.DataFrame(
        [{"Nodo": node_labels.get(n, n), "Entropia": round(v, 3), "Gruppo": "Più eterogenei"} for n, v in top]
        + [{"Nodo": node_labels.get(n, n), "Entropia": round(v, 3), "Gruppo": "Più omogenei"} for n, v in bottom]
    )
    return _df_to_html_table(df, max_rows=2 * top_n)


def _community_table_html(partition: dict, G) -> str:
    from collections import Counter, defaultdict
    members = defaultdict(list)
    for n, c in partition.items():
        members[c].append(n)
    rows = []
    for c, nodes in sorted(members.items(), key=lambda kv: -len(kv[1])):
        cats = Counter(G.nodes[n].get("category") for n in nodes)
        top_cat = cats.most_common(1)[0][0] if cats else "N/D"
        rows.append({"Comunità": c, "N. nodi": len(nodes), "Categoria prevalente": top_cat})
    return _df_to_html_table(pd.DataFrame(rows), max_rows=50)


def _betweenness_table_html(btw_per_node: dict, node_labels: dict, top_n: int = 15) -> str:
    rows = sorted(btw_per_node.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    df = pd.DataFrame(
        [{"Nodo": node_labels.get(n, n), "Betweenness": round(b, 4)} for n, b in rows]
    )
    return _df_to_html_table(df)


def _per_community_table_html(per_comunita: dict) -> str:
    rows = []
    for comm_id, vals in per_comunita.items():
        rows.append({
            "Comunità": comm_id,
            "Nodi": vals["n_nodi"],
            "Legami": vals["n_edge"],
            "Densità (link/nodi)": round(vals["densita_links_su_nodi"], 3),
            "Entropia media": round(vals["entropia_media"], 3),
        })
    return _df_to_html_table(pd.DataFrame(rows), max_rows=50)


def _rows_table_html(rows: list[dict], round_digits: int = 3, max_rows: int = 30) -> str:
    """Tabella generica da una lista di dict (es. robustness.attack_simulation)."""
    df = pd.DataFrame(rows)
    for col in df.select_dtypes(include="float").columns:
        df[col] = df[col].round(round_digits)
    return _df_to_html_table(df, max_rows=max_rows)


def _temporal_table_html(metrics_by_year: dict) -> str:
    rows = []
    for year, report in sorted(metrics_by_year.items()):
        rows.append({
            "Anno": year,
            "Nodi": report["densita"]["n_nodi"],
            "Legami": report["densita"]["n_edge"],
            "Densità (link/nodi)": round(report["densita"]["densita_links_su_nodi"], 3),
            "Entropia media": round(report["entropia_media"], 3),
            "N. comunità": report["n_comunita"],
        })
    return _df_to_html_table(pd.DataFrame(rows), max_rows=50)


def build_report(
    output_path: str,
    titolo: str,
    dataset_nome: str,
    G,
    metrics: dict,
    node_labels: dict | None = None,
    network_png_path: str | None = None,
    coarse_png_path: str | None = None,
    metrics_by_year: dict | None = None,
    executive_summary: str | None = None,
    evolution_gif_path: str | None = None,
    robustness_rows: list[dict] | None = None,
    dependency_rows: list[dict] | None = None,
    impact_rows: list[dict] | None = None,
    extra_context: dict | None = None,
) -> str:
    """
    Compila il template scheletro con i risultati e scrive il report HTML finale.
    Ogni argomento è opzionale (tranne output_path/titolo/dataset_nome/G/metrics):
    se mancante, la sezione corrispondente resta come placeholder nel report,
    pronta per essere compilata a mano o da un run successivo della pipeline.
    """
    node_labels = node_labels or {n: G.nodes[n].get("label", n) for n in G.nodes()}

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    template = env.get_template("report_template.html")

    context = dict(
        titolo=titolo,
        dataset_nome=dataset_nome,
        data_generazione=datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        n_nodi=metrics["densita"]["n_nodi"],
        n_edge=metrics["densita"]["n_edge"],
        densita_links_su_nodi=round(metrics["densita"]["densita_links_su_nodi"], 3),
        densita_standard=round(metrics["densita"]["densita_standard_0_1"], 4),
        diametro=metrics["diametro"]["diametro_componente_maggiore"],
        n_componenti=metrics["diametro"]["n_componenti"],
        n_comunita=metrics["n_comunita"],
        modularita=round(metrics["modularita"], 3) if metrics["modularita"] is not None else "N/D",
        entropia_media=round(metrics["entropia_media"], 3),
        top_degree_table=_degree_table_html(metrics["degree"], node_labels),
        entropy_table=_entropy_table_html(metrics["entropia_per_nodo"], node_labels),
        community_table=_community_table_html(metrics["comunita"], G),
        executive_summary=executive_summary,
    )

    # metriche introdotte dopo la prima versione: compilate solo se presenti
    clustering = metrics.get("clustering") or {}
    if clustering:
        context["clustering_medio"] = round(clustering["clustering_medio"], 3)
        context["transitivita"] = round(clustering["transitivita"], 3)
    if metrics.get("betweenness_per_nodo"):
        context["top_betweenness_table"] = _betweenness_table_html(
            metrics["betweenness_per_nodo"], node_labels)
    if metrics.get("per_comunita"):
        context["per_community_table"] = _per_community_table_html(metrics["per_comunita"])

    if network_png_path and os.path.exists(network_png_path):
        context["network_image_html"] = _img_to_base64_html(network_png_path)
    if coarse_png_path and os.path.exists(coarse_png_path):
        context["coarse_network_image_html"] = _img_to_base64_html(coarse_png_path)
    if metrics_by_year:
        context["temporal_table"] = _temporal_table_html(metrics_by_year)
    if evolution_gif_path and os.path.exists(evolution_gif_path):
        # la GIF animata embeddata in base64 resta animata nel browser
        context["evolution_gif_html"] = _img_to_base64_html(
            evolution_gif_path, mime="image/gif")
    if robustness_rows:
        context["robustness_table"] = _rows_table_html(robustness_rows)
    if dependency_rows:
        context["dependency_table"] = _rows_table_html(dependency_rows)
    if impact_rows:
        # impact_rows: righe già calcolate da impact.impact_table(...)["righe"]
        context["impact_table"] = _rows_table_html(impact_rows)

    if extra_context:
        context.update(extra_context)

    html = template.render(**context)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path
