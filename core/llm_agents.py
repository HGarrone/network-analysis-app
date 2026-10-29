"""
llm_agents.py
Nodi "agentici": decisioni della simulazione (accettazione di un legame,
in prospettiva anche migrazione o valutazione di coppie) delegate a un
modello linguistico. Modulo SEPARATO: se un provider non risponde o cambia
API, il resto del programma non ne risente — le regole classiche di
simulation.py restano il default.

Provider supportati (classe = un provider; aggiungerne uno = una classe
con lo stesso metodo .chat):
- OllamaClient  — modelli LOCALI via http://localhost:11434 (nessun dato
                  esce dalla macchina; consigliato per default).
- ClaudeClient  — API Anthropic (chiave incollata dall'utente in sessione,
                  mai da .env/variabili d'ambiente — mai salvata su disco).
- GeminiClient  — API Google (stessa regola: solo incolla-in-sessione).

PRIVACY: le funzioni di questo modulo inviano al modello SOLO il contesto
sintetico della simulazione (classi tipo "A"/"B", contatori di edge, id
fittizi "A0", "B3"): mai dati reali. Se in futuro si useranno per dati
veri (es. valutare coppie di enti con i loro nomi), preferire Ollama
locale: con i provider cloud il prompt lascia la macchina.

Modelli consigliati (testo/JSON, no vision/embedding):
- Ollama: qwen3, deepseek-r1:14b, gemma4, mistral, llama3.2
- Claude: claude-haiku-4-5-20251001 (veloce/economico, default),
          claude-sonnet-5 (più capace)
- Gemini: gemini-2.5-flash (default; il nome modello è comunque configurabile)
"""

from __future__ import annotations

import json
import re

import requests

# modelli locali adatti a decisioni testuali/JSON (esclusi vision/embedding)
SUGGESTED_OLLAMA_MODELS = ["qwen3:latest", "deepseek-r1:14b", "gemma4:latest",
                            "mistral:latest", "llama3.2:latest"]
SUGGESTED_CLAUDE_MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-5"]
SUGGESTED_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]

OLLAMA_URL = "http://localhost:11434"


# ---------------------------------------------------------------------------
# Provider (tutti espongono .chat(system, user) -> str)
# ---------------------------------------------------------------------------

class OllamaClient:
    """Modelli locali via Ollama (nessun dato lascia la macchina)."""

    def __init__(self, model: str = "llama3.2:latest", url: str = OLLAMA_URL,
                  temperature: float = 0.2, timeout: int = 120):
        self.model, self.url, self.temperature, self.timeout = model, url, temperature, timeout
        self.nome = f"ollama/{model}"

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(f"{self.url}/api/chat", timeout=self.timeout, json={
            "model": self.model, "stream": False,
            "options": {"temperature": self.temperature},
            "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}],
        })
        resp.raise_for_status()
        return resp.json()["message"]["content"]


class ClaudeClient:
    """API Anthropic (REST, nessuna dipendenza extra). Chiave: SOLO il
    parametro api_key, mai letta da variabili d'ambiente/.env — stessa scelta
    di massima sicurezza già adottata in pipeline video: la chiave vale solo
    per la sessione corrente, incollata dall'utente, mai persistita su disco
    né letta automaticamente dall'ambiente (anche in uso locale)."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001",
                  api_key: str | None = None, temperature: float = 0.2,
                  max_tokens: int = 512, timeout: int = 60):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("Chiave API Anthropic mancante: incollala nel campo dedicato.")
        self.model, self.temperature = model, temperature
        self.max_tokens, self.timeout = max_tokens, timeout
        self.nome = f"claude/{model}"

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages", timeout=self.timeout,
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                      "content-type": "application/json"},
            json={"model": self.model, "max_tokens": self.max_tokens,
                   "temperature": self.temperature, "system": system,
                   "messages": [{"role": "user", "content": user}]})
        resp.raise_for_status()
        return "".join(b.get("text", "") for b in resp.json()["content"])


class GeminiClient:
    """API Google Gemini (REST). Chiave: SOLO il parametro api_key, mai letta
    da variabili d'ambiente/.env — vedi nota di sicurezza in ClaudeClient."""

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None,
                  temperature: float = 0.2, timeout: int = 60):
        self.api_key = api_key
        if not self.api_key:
            raise ValueError("Chiave API Gemini mancante: incollala nel campo dedicato.")
        self.model, self.temperature, self.timeout = model, temperature, timeout
        self.nome = f"gemini/{model}"

    def chat(self, system: str, user: str) -> str:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.api_key}")
        resp = requests.post(url, timeout=self.timeout, json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": self.temperature},
        })
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def list_ollama_models(url: str = OLLAMA_URL, only_suggested: bool = True) -> list[str]:
    """Modelli installati in Ollama (vuota se il server non risponde);
    con only_suggested filtra ai soli modelli adatti a questo lavoro."""
    try:
        resp = requests.get(f"{url}/api/tags", timeout=5)
        resp.raise_for_status()
        names = [m["name"] for m in resp.json().get("models", [])]
    except requests.RequestException:
        return []
    if only_suggested:
        names = [n for n in names if n in SUGGESTED_OLLAMA_MODELS]
    return sorted(names)


def make_client(provider: str, model: str, api_key: str | None = None, **kwargs):
    """Factory unica per la GUI/script: provider 'ollama' | 'claude' | 'gemini'."""
    provider = provider.lower()
    if provider == "ollama":
        return OllamaClient(model=model, **kwargs)
    if provider == "claude":
        return ClaudeClient(model=model, api_key=api_key, **kwargs)
    if provider == "gemini":
        return GeminiClient(model=model, api_key=api_key, **kwargs)
    raise ValueError(f"Provider '{provider}' non riconosciuto (ollama/claude/gemini).")


# ---------------------------------------------------------------------------
# Risposte JSON robuste
# ---------------------------------------------------------------------------

def _strip_thinking(text: str) -> str:
    """Rimuove i blocchi <think>...</think> (deepseek-r1, qwen3 in modalità think)."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)


def extract_json(text: str) -> dict | None:
    """Estrae il primo oggetto JSON dalla risposta (tollera code fence,
    testo attorno, blocchi di ragionamento). None se non trovato."""
    text = _strip_thinking(text)
    text = re.sub(r"```(?:json)?", "", text)
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None  # oggetto malformato: prova il successivo
    return None


def ask_json(client, system: str, user: str, retries: int = 1) -> dict | None:
    """chat + parsing JSON, con un retry che ribadisce il formato."""
    text = client.chat(system, user)
    parsed = extract_json(text)
    for _ in range(retries):
        if parsed is not None:
            break
        text = client.chat(system, user + "\n\nRISPONDI SOLO con l'oggetto JSON richiesto.")
        parsed = extract_json(text)
    return parsed


# ---------------------------------------------------------------------------
# Aggancio alla simulazione: accettazione agentica
# ---------------------------------------------------------------------------

_ACCEPT_SYSTEM = (
    "Sei un agente in una simulazione di rete sociale. Ricevi una proposta di "
    "legame e decidi se accettarla in base alla tua classe, alla classe del "
    "proponente, al tipo di legame e allo stato attuale dei tuoi collegamenti. "
    "Rispondi SOLO con JSON: {\"accetta\": true|false, \"motivo\": \"...\"}")


class LLMAcceptance:
    """
    Callable da usare in SimulationRules.acceptance:
        rules.acceptance[("A", "b", None)] = LLMAcceptance(client, personas={...})
    - personas: {classe: descrizione testuale del comportamento} (opzionale;
      es. "A: preferisce legami 'a', accetta 'b' solo da chi è più connesso").
    - max_calls: budget di chiamate al modello; esaurito, si usa `default`.
    - cache: memorizza la decisione per situazioni identiche (classi, tipo,
      confronto dei conteggi) per non richiamare il modello inutilmente.
    Il log delle decisioni è in .log (lista di dict).
    """

    def __init__(self, client, personas: dict | None = None, max_calls: int = 50,
                  cache: bool = True, default: bool = True):
        self.client = client
        self.personas = personas or {}
        self.max_calls = max_calls
        self.cache_enabled = cache
        self.default = default
        self.calls = 0
        self._cache: dict = {}
        self.log: list[dict] = []

    def _situazione(self, G, ricevente, proponente, tipo):
        from .simulation import count_typed_edges
        cr = G.nodes[ricevente].get("classe")
        cp = G.nodes[proponente].get("classe")
        situaz = {
            "mia_classe": cr, "classe_proponente": cp, "tipo_legame": tipo,
            "miei_edge_per_tipo": {t: count_typed_edges(G, ricevente, t)
                                     for t in {str(d.get("layer")) for _, _, d in G.edges(data=True)} or set()},
            "edge_proponente_stesso_tipo": count_typed_edges(G, proponente, tipo),
            "mio_degree": G.degree(ricevente), "degree_proponente": G.degree(proponente),
        }
        if cr in self.personas:
            situaz["mio_comportamento"] = self.personas[cr]
        return situaz

    def decide(self, G, ricevente, proponente, tipo) -> bool:
        situaz = self._situazione(G, ricevente, proponente, tipo)
        key = json.dumps({k: v for k, v in situaz.items()}, sort_keys=True, default=str)
        if self.cache_enabled and key in self._cache:
            return self._cache[key]
        if self.calls >= self.max_calls:
            return self.default
        self.calls += 1
        try:
            parsed = ask_json(self.client, _ACCEPT_SYSTEM,
                               "Situazione:\n" + json.dumps(situaz, ensure_ascii=False)
                               + "\nAccetti il legame proposto?")
        except requests.RequestException as e:
            self.log.append({"errore": str(e), **situaz})
            return self.default
        decisione = bool(parsed.get("accetta", self.default)) if parsed else self.default
        self.log.append({**situaz, "accetta": decisione,
                          "motivo": (parsed or {}).get("motivo", "")})
        if self.cache_enabled:
            self._cache[key] = decisione
        return decisione

    def __call__(self, G, ricevente, proponente):
        # SimulationRules chiama acceptance[(classe, tipo, ...)](G, ric, prop):
        # il tipo è nella chiave della regola; qui serve richiamare decide con
        # il tipo giusto -> usare bind_tipo() per fissarlo.
        raise TypeError("Usa bind_tipo(tipo) per ottenere la callable da mettere "
                         "in SimulationRules.acceptance.")

    def bind_tipo(self, tipo: str):
        """Callable (G, ricevente, proponente) -> bool con il tipo fissato."""
        return lambda G, ric, prop: self.decide(G, ric, prop, tipo)


def agentic_acceptance_rules(client, node_classes: list, edge_types: list,
                               personas: dict | None = None, max_calls: int = 50,
                               default: bool = True) -> tuple[dict, LLMAcceptance]:
    """
    Costruisce il dict acceptance completo per SimulationRules: OGNI
    (classe_ricevente, tipo, qualunque proponente) decisa dall'agente LLM,
    con budget condiviso e cache. Ritorna (acceptance, oggetto LLMAcceptance
    per leggere log e numero di chiamate).
    """
    agente = LLMAcceptance(client, personas=personas, max_calls=max_calls, default=default)
    acceptance = {(cl, t, None): agente.bind_tipo(t)
                  for cl in node_classes for t in edge_types}
    return acceptance, agente
