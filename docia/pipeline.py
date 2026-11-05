"""
Pipeline DocIA local : PDF -> texte -> LLM (JSON) -> validation -> règles + analyse LLM -> résultat.

Deux détections de fraude complémentaires :
- les règles Python (rules.py) : déterministes, auditables, le filet de sécurité ;
- l'analyse LLM (prompts/analyse_v1.txt) : le modèle lit le dossier entier, juge sa cohérence
  et explique chaque incohérence en langage clair pour le conseiller.
"""

import json
import logging
from pathlib import Path

from pydantic import ValidationError
from pypdf import PdfReader

from docia.llm import MODEL, PROVIDER, chat_json
from docia.rules import check_dossier
from docia.schema import AnalyseLLM, Extraction

PROMPT_FILE = Path("prompts/extract_v1.txt")
PROMPT_VERSION = PROMPT_FILE.stem
SYSTEM_PROMPT = PROMPT_FILE.read_text(encoding="utf-8")
ANALYSE_FILE = Path("prompts/analyse_v1.txt")
ANALYSE_PROMPT = ANALYSE_FILE.read_text(encoding="utf-8")
SEUIL_CONFIANCE = 0.7  # en dessous : revue humaine

log = logging.getLogger("docia")


def pdf_to_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def _new_trace(name: str, etape: str, prompt: str) -> dict:
    return {"fichier": name, "etape": etape, "prompt": prompt, "modele": MODEL, "provider": PROVIDER,
            "appels": 0, "tokens_in": 0, "tokens_out": 0, "latence_s": 0.0, "cout_usd": 0.0}


def _call_validated(system: str, user: str, model_cls, trace: dict):
    """Appel LLM + validation Pydantic, avec une relance si le JSON est invalide."""
    for _ in range(2):
        call = chat_json(system, user)
        trace["appels"] += 1
        trace["tokens_in"] += call.tokens_in
        trace["tokens_out"] += call.tokens_out
        trace["latence_s"] += call.latency_s
        trace["cout_usd"] += call.cost_usd
        try:
            result = model_cls.model_validate(json.loads(call.content))
            trace["json_valide"] = True
            return result
        except (json.JSONDecodeError, ValidationError) as err:
            log.warning("JSON invalide (%s) : %s", trace["fichier"], err)
    trace["json_valide"] = False
    return None


def extract(path: Path) -> tuple[Extraction | None, dict]:
    """Étape 4 : le LLM extrait les champs d'UN document."""
    trace = _new_trace(path.name, "extraction", PROMPT_VERSION)
    text = pdf_to_text(path)
    result = _call_validated(SYSTEM_PROMPT, f"Document :\n<<<\n{text}\n>>>", Extraction, trace)
    return result, trace


def analyse_llm(folder: Path) -> tuple[AnalyseLLM | None, dict]:
    """Étape 6 : le LLM lit les documents du dossier ensemble et juge leur cohérence."""
    trace = _new_trace(folder.name, "analyse", ANALYSE_FILE.stem)
    parts = [f"=== {pdf.name} ===\n{pdf_to_text(pdf)}" for pdf in sorted(folder.glob("*.pdf"))]
    user = "Documents du dossier :\n<<<\n" + "\n\n".join(parts) + "\n>>>"
    result = _call_validated(ANALYSE_PROMPT, user, AnalyseLLM, trace)
    return result, trace


def process_dossier(folder: Path) -> dict:
    extractions, traces = {}, []
    for pdf in sorted(folder.glob("*.pdf")):
        result, trace = extract(pdf)
        traces.append(trace)
        if result:
            extractions[pdf.name] = result

    alerts = check_dossier(list(extractions.values()))
    analyse, trace = analyse_llm(folder)
    traces.append(trace)

    confiance_min = min((e.confiance for e in extractions.values()), default=0.0)
    alertes_llm = [a.model_dump() for a in analyse.alertes] if analyse else []
    revue_humaine = (bool(alerts) or bool(alertes_llm) or confiance_min < SEUIL_CONFIANCE
                     or len(extractions) < sum(t["etape"] == "extraction" for t in traces))
    return {
        "dossier": folder.name,
        "extractions": {k: v.model_dump() for k, v in extractions.items()},
        "alertes": alerts,                      # détectées par les règles Python
        "analyse_llm": {                        # détectées par le LLM, avec explications
            "coherent": analyse.coherent if analyse else None,
            "alertes": alertes_llm,
        },
        "confiance_min": confiance_min,
        "revue_humaine": revue_humaine,
        "traces": traces,
    }
