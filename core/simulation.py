"""
simulation.py
Simulazioni su rete, in due famiglie:

1. FRAMEWORK A CLASSI DI NODI CON REGOLE (SimulationRules + simulate):
   si definiscono CLASSI di nodi (es. A, B, C) e TIPI di edge (es. a, b, c);
   per ogni coppia di classi una lista di PREFERENZE (tipi di edge in ordine
   di tentativo) e, opzionalmente, condizioni di ACCETTAZIONE per singolo
   (classe ricevente, tipo, classe proponente) e una regola di MIGRAZIONE
   quando nessun tipo viene accettato. Il risultato è un nx.MultiGraph con
   l'attributo `layer` = tipo di edge: si analizza direttamente con
   multiplex.py (flatten, multiplexity, overlap...).

   Esempio (le regole descritte nel brief utente, simplificate):
       regole = SimulationRules(
           node_classes=["A", "B", "C"],
           edge_types=["a", "b", "c"],
           preferences={
               ("A", "A"): ["a", "b"], ("A", "B"): ["a", "b"], ("A", "C"): ["a", "b"],
               ("B", "A"): ["b", "c"], ("B", "B"): ["b"],      ("B", "C"): ["a", "b"],
               ("C", "A"): ["b", "a"], ("C", "B"): ["b", "a"], ("C", "C"): ["a", "b"],
           },
           acceptance={
               # A accetta 'b' da un altro A solo se l'altro ha più edge 'a'
               # con nodi A di lui (o circa pari):
               ("A", "b", "A"): lambda G, ricevente, proponente: (
                   count_typed_edges(G, proponente, "a", partner_class="A")
                   >= count_typed_edges(G, ricevente, "a", partner_class="A")),
           },
       )
       G = simulate(regole, n_per_class={"A": 10, "B": 10, "C": 10}, steps=500)

   Le regole possono essere espresse come truth-table (dict), funzioni, o in
   futuro apprese/ML o agentiche (nodi simulati da AI): basta sostituire le
   callable di acceptance/migration senza toccare il motore.

2. MODELLI CLASSICI DI DINAMICA SU RETE:
   - granovetter_cascade: cascate di adozione con soglie individuali
   - ising_dynamics: spin ±1 con dinamica di Glauber (consenso/polarizzazione)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import networkx as nx


# ---------------------------------------------------------------------------
# Utilità per scrivere condizioni di accettazione
# ---------------------------------------------------------------------------

def count_typed_edges(G: nx.MultiGraph, node, edge_type: str,
                       partner_class: str | None = None) -> int:
    """Quanti edge di un certo tipo ha `node` (opzionalmente solo verso
    partner di una data classe). Comodo dentro le lambda di acceptance."""
    if node not in G:
        return 0
    count = 0
    for _, nbr, d in G.edges(node, data=True):
        if str(d.get("layer")) != str(edge_type):
            continue
        if partner_class is not None and G.nodes[nbr].get("classe") != partner_class:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Framework a classi di nodi con regole
# ---------------------------------------------------------------------------

@dataclass
class SimulationRules:
    """
    Regole della simulazione, tutte sostituibili senza toccare il motore:
    - node_classes / edge_types: nomi delle classi e dei tipi di legame.
    - preferences: {(classe_proponente, classe_ricevente): [tipi in ordine
      di tentativo]} — la truth-table delle preferenze.
    - acceptance: {(classe_ricevente, tipo, classe_proponente): callable
      (G, ricevente, proponente) -> bool}. Se una chiave manca si usa
      default_accept (True). Chiavi parziali ammesse con None come jolly:
      (classe_ricevente, tipo, None) vale per qualunque proponente.
    - migration: callable(G, nodo, rng) -> nuovo partner proposto (o None).
      Default: un nodo a caso di un'altra componente (il nodo 'migra').
    - allow_duplicate_edges: se False (default) non ripropone un tipo già
      esistente tra i due nodi.
    """
    node_classes: list
    edge_types: list
    preferences: dict
    acceptance: dict = field(default_factory=dict)
    migration: object = None
    allow_duplicate_edges: bool = False

    def accepts(self, G, ricevente, tipo, proponente) -> bool:
        cr = G.nodes[ricevente].get("classe")
        cp = G.nodes[proponente].get("classe")
        for key in ((cr, tipo, cp), (cr, tipo, None)):
            if key in self.acceptance:
                return bool(self.acceptance[key](G, ricevente, proponente))
        return True  # default: accetta


def _default_migration(G, node, rng):
    """Migrazione di default: prova un nodo a caso fuori dalla componente."""
    comp = nx.node_connected_component(G, node) if G.degree(node) else {node}
    fuori = [n for n in G.nodes() if n not in comp]
    return rng.choice(fuori) if fuori else None


def simulate(rules: SimulationRules, n_per_class: dict | None = None,
              steps: int = 500, seed: int = 42, G0: nx.MultiGraph | None = None) -> nx.MultiGraph:
    """
    Motore: a ogni passo un nodo a caso propone un legame a un partner a
    caso, tentando i tipi di edge nell'ordine delle preferenze per la coppia
    di classi; il primo tipo accettato crea l'edge (layer=tipo). Se nessuno
    viene accettato, scatta la regola di migrazione e si ritenta una volta
    col nuovo partner. Parte da G0 (se dato) o da n_per_class nodi isolati
    con attributi classe/label. Ritorna il MultiGraph finale (nuovo).
    """
    rng = random.Random(seed)
    if G0 is not None:
        G = G0.copy()
    else:
        if not n_per_class:
            raise ValueError("Servono n_per_class oppure un grafo di partenza G0.")
        G = nx.MultiGraph()
        for classe, n in n_per_class.items():
            for i in range(n):
                nid = f"{classe}{i}"
                G.add_node(nid, classe=classe, label=nid)

    nodes = list(G.nodes())
    if len(nodes) < 2:
        return G

    def try_pair(u, v) -> bool:
        cu, cv = G.nodes[u].get("classe"), G.nodes[v].get("classe")
        for tipo in rules.preferences.get((cu, cv), []):
            if not rules.allow_duplicate_edges and G.has_edge(u, v):
                if any(str(d.get("layer")) == str(tipo) for d in G[u][v].values()):
                    continue
            if rules.accepts(G, v, tipo, u):
                G.add_edge(u, v, layer=str(tipo))
                return True
        return False

    migration = rules.migration or _default_migration
    for _ in range(steps):
        u = rng.choice(nodes)
        v = rng.choice([n for n in nodes if n != u])
        if not try_pair(u, v):
            alt = migration(G, u, rng)
            if alt is not None and alt != u:
                try_pair(u, alt)

    from .multiplex import update_node_layers  # import locale per evitare cicli
    return update_node_layers(G)


# ---------------------------------------------------------------------------
# Modelli classici di dinamica su rete
# ---------------------------------------------------------------------------

def granovetter_cascade(G: nx.Graph, thresholds, seeds: list,
                          max_steps: int = 100) -> dict:
    """
    Cascata di adozione alla Granovetter: un nodo adotta quando la frazione
    di vicini che hanno già adottato supera la sua soglia individuale.
    thresholds: float unico oppure {nodo: soglia in [0,1]}.
    Ritorna {adottanti: {nodo: passo di adozione}, storia: [n adottanti per
    passo], frazione_finale}.
    """
    thr = thresholds if isinstance(thresholds, dict) else {n: float(thresholds) for n in G.nodes()}
    adopted = {s: 0 for s in seeds if s in G}
    history = [len(adopted)]
    for step in range(1, max_steps + 1):
        nuovi = []
        for n in G.nodes():
            if n in adopted:
                continue
            vicini = list(G.neighbors(n))
            if not vicini:
                continue
            frac = sum(1 for v in vicini if v in adopted) / len(vicini)
            if frac >= thr.get(n, 1.0):
                nuovi.append(n)
        if not nuovi:
            break
        for n in nuovi:
            adopted[n] = step
        history.append(len(adopted))
    return {"adottanti": adopted, "storia": history,
            "frazione_finale": round(len(adopted) / G.number_of_nodes(), 3) if G.number_of_nodes() else 0.0}


def schelling_segregation(G: nx.Graph, classes: tuple = ("A", "B"),
                            tolerance: float = 0.5, empty_fraction: float = 0.1,
                            steps: int = 2000, seed: int = 42,
                            assignment: dict | None = None) -> dict:
    """
    Modello di Schelling su rete: gli agenti (di `classes`) occupano i nodi,
    una quota empty_fraction resta vuota; un agente è INFELICE se la frazione
    di vicini occupati della sua stessa classe è sotto `tolerance`, e migra
    su un nodo vuoto a caso. Mostra come tolleranze anche miti producano
    segregazione (indice = frazione media di vicini della stessa classe).
    assignment: {nodo: classe|None} per partire da una configurazione data.
    Ritorna {assegnazione_finale, indice_segregazione, storia_indice, n_mosse}.
    """
    rng = random.Random(seed)
    nodes = list(G.nodes())
    if assignment is None:
        assignment = {}
        shuffled = nodes[:]
        rng.shuffle(shuffled)
        n_empty = int(len(nodes) * empty_fraction)
        for i, n in enumerate(shuffled):
            assignment[n] = None if i < n_empty else classes[i % len(classes)]
    else:
        assignment = dict(assignment)

    def same_class_fraction(n):
        vicini = [v for v in G.neighbors(n) if assignment.get(v) is not None]
        if not vicini:
            return 1.0  # nessun vicino occupato: nessun motivo di migrare
        return sum(1 for v in vicini if assignment[v] == assignment[n]) / len(vicini)

    def segregation_index():
        vals = [same_class_fraction(n) for n in nodes if assignment.get(n) is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    history = [segregation_index()]
    moves = 0
    occupied = [n for n in nodes if assignment[n] is not None]
    for step in range(steps):
        n = rng.choice(occupied)
        if same_class_fraction(n) >= tolerance:
            continue
        empties = [v for v in nodes if assignment[v] is None]
        if not empties:
            break
        dest = rng.choice(empties)
        assignment[dest], assignment[n] = assignment[n], None
        occupied[occupied.index(n)] = dest
        moves += 1
        if step % max(1, steps // 50) == 0:
            history.append(segregation_index())
    history.append(segregation_index())
    return {"assegnazione_finale": assignment, "indice_segregazione": history[-1],
            "storia_indice": history, "n_mosse": moves}


def ising_dynamics(G: nx.Graph, beta: float = 1.0, steps: int = 2000,
                    seed: int = 42, init: dict | None = None,
                    weight: str | None = "weight") -> dict:
    """
    Modello di Ising con dinamica di Glauber sulla rete: ogni nodo ha uno
    spin ±1 (es. adotta/non adotta, opinione A/B) e tende ad allinearsi ai
    vicini; beta = 1/temperatura (alto = forte conformismo, basso = rumore).
    Ritorna {spin_finali, magnetizzazione (media spin), storia_magnetizzazione}.
    """
    rng = random.Random(seed)
    nodes = list(G.nodes())
    if not nodes:
        return {"spin_finali": {}, "magnetizzazione": 0.0, "storia_magnetizzazione": []}
    spin = dict(init) if init else {n: rng.choice((-1, 1)) for n in nodes}
    history = []
    for step in range(steps):
        n = rng.choice(nodes)
        campo = sum((G[n][v].get(weight, 1) if weight else 1) * spin[v]
                    for v in G.neighbors(n))
        delta_e = 2 * spin[n] * campo
        if delta_e <= 0 or rng.random() < math.exp(-beta * delta_e):
            spin[n] = -spin[n]
        if step % max(1, steps // 100) == 0:
            history.append(round(sum(spin.values()) / len(nodes), 4))
    return {"spin_finali": spin,
            "magnetizzazione": round(sum(spin.values()) / len(nodes), 4),
            "storia_magnetizzazione": history}
