"""
link_prediction_ml.py
Link prediction SUPERVISIONATA: un modello impara dai passaggi anno→anno
quali coppie si collegheranno, usando come feature i punteggi dei metodi
classici (link_prediction.METHODS) più i degree dei due nodi.

Modulo SEPARATO da link_prediction.py: la versione classica resta
autonoma e questa si può modificare/sostituire senza toccarla.

Come funziona (hold-out temporale, riusa temporal + projections):
1. per ogni transizione anno y_i -> y_{i+1} (tranne l'ultima disponibile):
   - feature delle coppie candidate sulla proiezione cumulativa a y_i
   - etichetta = 1 se la coppia è collegata nella proiezione a y_{i+1}
2. si allena una regressione logistica (scikit-learn se installato,
   altrimenti un'implementazione interna in puro numpy — nessuna
   dipendenza obbligatoria in più)
3. si prevedono le coppie candidate sull'ULTIMA rete cumulativa
   (= suggerimenti per il futuro), con probabilità.

Espandibile: nuove feature = una entry in FEATURES; altro modello = si
sostituisce _fit/_predict_proba.
"""

from __future__ import annotations

import networkx as nx
import numpy as np

from . import link_prediction as lp

try:
    from sklearn.linear_model import LogisticRegression
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False


# ---------------------------------------------------------------------------
# Feature per coppia (nome -> funzione(G, pairs) -> {coppia: valore})
# ---------------------------------------------------------------------------

def _method_scores(method):
    def scorer(G, pairs):
        return {(u, v): s for u, v, s in lp.METHODS[method](G, pairs)}
    return scorer


def _degree_sum(G, pairs):
    return {(u, v): G.degree(u) + G.degree(v) for u, v in pairs}


FEATURES = {name: _method_scores(name) for name in lp.METHODS}
FEATURES["degree_sum"] = _degree_sum


def pair_features(G: nx.Graph, pairs: list) -> np.ndarray:
    """Matrice (n_coppie × n_feature) nell'ordine di FEATURES."""
    columns = []
    for fn in FEATURES.values():
        scores = fn(G, pairs)
        columns.append([float(scores.get(p, 0.0)) for p in pairs])
    return np.array(columns, dtype=float).T


# ---------------------------------------------------------------------------
# Modello: scikit-learn se c'è, altrimenti logistica interna (numpy)
# ---------------------------------------------------------------------------

class _SimpleLogit:
    """Regressione logistica minimale (discesa del gradiente, feature
    standardizzate): fallback senza dipendenze quando manca scikit-learn."""

    def __init__(self, lr: float = 0.1, iters: int = 800):
        self.lr, self.iters = lr, iters
        self.w = self.b = self.mu = self.sigma = None

    def _standardize(self, X):
        return (X - self.mu) / self.sigma

    def fit(self, X, y):
        self.mu = X.mean(axis=0)
        self.sigma = X.std(axis=0)
        self.sigma[self.sigma == 0] = 1.0
        Xs = self._standardize(X)
        n, d = Xs.shape
        self.w, self.b = np.zeros(d), 0.0
        for _ in range(self.iters):
            p = 1 / (1 + np.exp(-(Xs @ self.w + self.b)))
            grad_w = Xs.T @ (p - y) / n
            grad_b = float((p - y).mean())
            self.w -= self.lr * grad_w
            self.b -= self.lr * grad_b
        return self

    def predict_proba_pos(self, X):
        Xs = self._standardize(X)
        return 1 / (1 + np.exp(-(Xs @ self.w + self.b)))


def _fit(X, y):
    if _HAS_SKLEARN:
        model = LogisticRegression(max_iter=1000, class_weight="balanced")
        model.fit(X, y)
        return model, "sklearn.LogisticRegression"
    return _SimpleLogit().fit(X, y), "logistica interna (numpy)"


def _predict_proba_pos(model, X):
    if _HAS_SKLEARN and isinstance(model, LogisticRegression):
        return model.predict_proba(X)[:, 1]
    return model.predict_proba_pos(X)


# ---------------------------------------------------------------------------
# Training temporale + previsione
# ---------------------------------------------------------------------------

def supervised_link_prediction(G_bipartite: nx.Graph, on: str = "ente",
                                 weight_mode: str = "count", top_k: int = 20,
                                 max_neg_ratio: int = 5, seed: int = 42) -> dict:
    """
    Allena sulle transizioni anno→anno disponibili e suggerisce le coppie
    più probabili sull'ultima rete cumulativa. max_neg_ratio limita i
    negativi campionati (coppie candidate che NON si sono collegate) a
    N volte i positivi, per non sbilanciare il training.
    Ritorna {previsioni, n_esempi, n_positivi, modello, anni_usati}.
    """
    from . import temporal, projections  # import locale per evitare cicli

    rng = np.random.default_rng(seed)
    graphs = temporal.split_by_year(G_bipartite, mode="cumulative")
    years = sorted(graphs)
    if len(years) < 2:
        raise ValueError("Servono almeno due anni per allenare (transizioni anno→anno).")

    def key(u, v):
        return (u, v) if str(u) <= str(v) else (v, u)

    X_rows, y_rows = [], []
    for y1, y2 in zip(years, years[1:]):
        G1 = projections.project(graphs[y1], on=on, weight_mode=weight_mode)
        G2 = projections.project(graphs[y2], on=on, weight_mode=weight_mode)
        cands = [key(u, v) for u, v in lp.candidate_pairs(G1)]
        if not cands:
            continue
        future = {key(u, v) for u, v in G2.edges()}
        pos = [p for p in cands if p in future]
        neg = [p for p in cands if p not in future]
        if len(neg) > max_neg_ratio * max(len(pos), 1):
            idx = rng.choice(len(neg), size=max_neg_ratio * max(len(pos), 1), replace=False)
            neg = [neg[i] for i in idx]
        pairs = pos + neg
        X_rows.append(pair_features(G1, pairs))
        y_rows.append(np.array([1] * len(pos) + [0] * len(neg), dtype=float))

    if not X_rows or not any(y.sum() for y in y_rows):
        raise ValueError("Nessun nuovo legame nelle transizioni disponibili: "
                          "impossibile allenare (nessun esempio positivo).")
    X = np.vstack(X_rows)
    y = np.concatenate(y_rows)
    model, model_name = _fit(X, y)

    # previsione sull'ultima rete cumulativa
    G_last = projections.project(graphs[years[-1]], on=on, weight_mode=weight_mode)
    cands = lp.candidate_pairs(G_last)
    if not cands:
        return {"previsioni": [], "n_esempi": len(y), "n_positivi": int(y.sum()),
                "modello": model_name, "anni_usati": years}
    probs = _predict_proba_pos(model, pair_features(G_last, cands))
    order = np.argsort(-probs)[:top_k]
    previsioni = [{"u": cands[i][0], "v": cands[i][1],
                    "label_u": G_last.nodes[cands[i][0]].get("label", cands[i][0]),
                    "label_v": G_last.nodes[cands[i][1]].get("label", cands[i][1]),
                    "probabilita": round(float(probs[i]), 4)}
                   for i in order]
    return {"previsioni": previsioni, "n_esempi": len(y), "n_positivi": int(y.sum()),
            "modello": model_name, "anni_usati": years}
