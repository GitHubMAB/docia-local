"""
Client LLM unique, compatible OpenAI, pour deux fournisseurs gratuits :

- gemini : API Gemini de Google (offre gratuite, clé créée sur Google AI Studio, sans carte bancaire).
           Gemini est cité dans l'offre Meilleurtaux. Ne pas y envoyer de vraies données personnelles :
           sur l'offre gratuite, les échanges peuvent servir à améliorer les modèles de Google.
- ollama : modèle open source qui tourne sur la machine (ton PC ou le runner GitHub Actions).
           Gratuit, illimité, aucune clé, aucune donnée ne sort de la machine.

Le code applicatif ne change pas : seule la configuration (variables d'environnement) change.
C'est le même principe que basculer de dev à prod vers Azure OpenAI / Foundry.
"""

import os
import time
from dataclasses import dataclass

from openai import OpenAI

PROVIDERS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
    },
    "ollama": {
        "base_url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
        "api_key_env": None,  # Ollama n'exige pas de clé
        "default_model": "qwen2.5:3b",
    },
}

PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
CONF = PROVIDERS[PROVIDER]
MODEL = os.getenv("LLM_MODEL") or CONF["default_model"]

# Prix en $ par million de tokens, à renseigner selon le modèle visé en production.
# 0 par défaut : les deux options sont gratuites. Mets les prix d'Azure OpenAI pour simuler la facture.
PRICE_IN = float(os.getenv("PRICE_IN_PER_M", "0"))
PRICE_OUT = float(os.getenv("PRICE_OUT_PER_M", "0"))

_api_key = os.environ[CONF["api_key_env"]] if CONF["api_key_env"] else "ollama"
# max_retries : relance automatique avec attente progressive sur les erreurs 429 (quota gratuit).
client = OpenAI(base_url=CONF["base_url"], api_key=_api_key, timeout=300, max_retries=5)


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
        # Le serveur n'a pas renvoyé du JSON OpenAI : service fermé, proxy, mauvaise URL…
        raise RuntimeError(
            f"Réponse inattendue de {CONF['base_url']} (HTTP {raw.status_code}, "
            f"content-type {raw.headers.get('content-type')}) :\n{resp[:500]}"
        )
    usage = resp.usage
    content = resp.choices[0].message.content or "{}"
    # Certains modèles entourent le JSON de ```json ... ``` : on nettoie.
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return LLMCall(
        content=content,
        latency_s=time.perf_counter() - start,
        tokens_in=usage.prompt_tokens if usage else 0,
        tokens_out=usage.completion_tokens if usage else 0,
    )
