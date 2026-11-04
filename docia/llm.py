"""
Client LLM unique, compatible OpenAI, pour deux fournisseurs gratuits :

- github : GitHub Models (gratuit, quotas journaliers). Marche dans GitHub Actions et en local avec un PAT.
- ollama : modèle local sur ton PC (gratuit, illimité, aucune donnée ne sort de ta machine).

Le code applicatif ne change pas : seule la configuration (variables d'environnement) change.
C'est le même principe que basculer de dev à prod vers Azure OpenAI / Foundry.
"""

import os
import time
from dataclasses import dataclass

from openai import OpenAI

PROVIDERS = {
    "github": {
        "base_url": "https://models.github.ai/inference",
        "api_key_env": "GITHUB_TOKEN",
        "default_model": "openai/gpt-4o-mini",
    },
    "ollama": {
        "base_url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
        "api_key_env": None,  # Ollama n'exige pas de clé
        "default_model": "qwen2.5:3b",
    },
}

PROVIDER = os.getenv("LLM_PROVIDER", "github")
CONF = PROVIDERS[PROVIDER]
MODEL = os.getenv("LLM_MODEL", CONF["default_model"])

# Prix en $ par million de tokens, à renseigner selon le modèle visé en production.
# 0 par défaut : GitHub Models et Ollama sont gratuits. Mets les prix d'Azure OpenAI pour simuler la facture.
PRICE_IN = float(os.getenv("PRICE_IN_PER_M", "0"))
PRICE_OUT = float(os.getenv("PRICE_OUT_PER_M", "0"))

_api_key = os.environ[CONF["api_key_env"]] if CONF["api_key_env"] else "ollama"
client = OpenAI(base_url=CONF["base_url"], api_key=_api_key, timeout=120, max_retries=3)


@dataclass
class LLMCall:
    content: str
    latency_s: float
    tokens_in: int
    tokens_out: int

    @property
    def cost_usd(self) -> float:
        return self.tokens_in / 1e6 * PRICE_IN + self.tokens_out / 1e6 * PRICE_OUT


def chat_json(system: str, user: str) -> LLMCall:
    """Appel au LLM avec sortie JSON imposée et température 0 (résultats stables)."""
    start = time.perf_counter()
    raw = client.chat.completions.with_raw_response.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    resp = raw.parse()
    if isinstance(resp, str):
        # Le serveur n'a pas renvoyé du JSON OpenAI : proxy d'entreprise, mauvaise URL, page d'erreur…
        raise RuntimeError(
            f"Réponse inattendue de {CONF['base_url']} (HTTP {raw.status_code}, "
            f"content-type {raw.headers.get('content-type')}) :\n{resp[:500]}"
        )
    usage = resp.usage
    return LLMCall(
        content=resp.choices[0].message.content or "{}",
        latency_s=time.perf_counter() - start,
        tokens_in=usage.prompt_tokens if usage else 0,
        tokens_out=usage.completion_tokens if usage else 0,
    )