"""
viz3d.py
Vista 3D interattiva (Plotly) di una rete multiplex: ogni layer su un
proprio piano orizzontale (z fisso), le STESSE coordinate (x, y) per ogni
nodo su tutti i layer (calcolate una volta sola sulla rete "appiattita"),
con linee verticali tratteggiate a collegare le occorrenze dello stesso
nodo su layer diversi — la visualizzazione standard in letteratura per le
reti multiplex/multilayer (un piano per layer impilati sull'asse z).

Restituisce una plotly.graph_objects.Figure, incorporabile in Streamlit
con st.plotly_chart(fig, width='stretch') — ruotabile/zoommabile nel browser
a differenza delle viste 2D esistenti (matplotlib/vis.js).
"""

from __future__ import annotations

import networkx as nx
import plotly.graph_objects as go

from . import multiplex as multiplex_mod
from .layout import compute_layout


def multiplex_3d_figure(M: nx.MultiGraph, layout_method: str = "spring",
                         layer_spacing: float = 1.0, show_labels: bool = False,
                         show_interlayer_links: bool = True) -> go.Figure:
    """
    Costruisce la figura 3D del multiplex M (vedi docstring modulo).
    layout_method: come layout.compute_layout ('spring'/'fa2'/'kamada_kawai'),
    calcolato UNA VOLTA sulla rete appiattita (tutti i layer uniti) così le
    coordinate (x, y) di un nodo sono le stesse su ogni piano.
    """
    layers = multiplex_mod.get_layers(M)
    if not layers:
        raise ValueError("Il multiplex non ha layer (nessun edge con attributo 'layer').")

    flat = multiplex_mod.flatten(M, strategy="count", merge_scope="all", include_isolated=True)
    pos = compute_layout(flat, method=layout_method)

    fig = go.Figure()

    for i, layer in enumerate(layers):
        z = i * layer_spacing
        edge_x, edge_y, edge_z = [], [], []
        for u, v, d in M.edges(data=True):
            if str(d.get("layer")) != layer or u not in pos or v not in pos:
                continue
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]
            edge_z += [z, z, None]
        fig.add_trace(go.Scatter3d(
            x=edge_x, y=edge_y, z=edge_z, mode="lines",
            line=dict(color="rgba(120,120,120,0.5)", width=2),
            hoverinfo="none", showlegend=False, name=f"edge_{layer}"))

        layer_nodes = [n for n in M.nodes()
                       if layer in (M.nodes[n].get("layers") or []) and n in pos]
        fig.add_trace(go.Scatter3d(
            x=[pos[n][0] for n in layer_nodes],
            y=[pos[n][1] for n in layer_nodes],
            z=[z for _ in layer_nodes],
            mode="markers+text" if show_labels else "markers",
            marker=dict(size=5, color=[M.nodes[n].get("viz_color", "#4C72B0") for n in layer_nodes],
                        line=dict(width=0.5, color="white")),
            text=[str(M.nodes[n].get("label", n)) for n in layer_nodes] if show_labels else None,
            textposition="top center",
            hovertext=[str(M.nodes[n].get("label", n)) for n in layer_nodes],
            hoverinfo="text",
            name=f"layer: {layer}"))

    if show_interlayer_links:
        link_x, link_y, link_z = [], [], []
        for n in M.nodes():
            if n not in pos:
                continue
            node_layers = [l for l in (M.nodes[n].get("layers") or []) if l in layers]
            if len(node_layers) < 2:
                continue
            x, y = pos[n]
            zs = sorted(layers.index(l) * layer_spacing for l in node_layers)
            for z0, z1 in zip(zs[:-1], zs[1:]):
                link_x += [x, x, None]
                link_y += [y, y, None]
                link_z += [z0, z1, None]
        if link_x:
            fig.add_trace(go.Scatter3d(
                x=link_x, y=link_y, z=link_z, mode="lines",
                line=dict(color="rgba(50,50,50,0.35)", width=1, dash="dash"),
                hoverinfo="none", showlegend=False, name="stesso nodo tra layer"))

    fig.update_layout(
        scene=dict(
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            zaxis=dict(title="layer", tickmode="array",
                       tickvals=[i * layer_spacing for i in range(len(layers))],
                       ticktext=layers),
        ),
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(itemsizing="constant"),
    )
    return fig
