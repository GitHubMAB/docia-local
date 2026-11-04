"""
Pipeline DocIA local : PDF -> texte -> LLM (JSON) -> validation -> règles -> résultat.

Correspond aux étapes 3 à 7 du cas pratique, sans Azure.
"""

import json
import logging
from pathlib import Path

from pydantic import ValidationError
from pypdf import PdfReader

from docia.llm import MODEL, PROVIDER, chat_json
from docia.rules import check_dossier
from docia.schema import Extraction

PROMPT_FILE = Path("prompts/extract_v1.txt")
PROMPT_VERSION = PROMPT_FILE.stem
SYSTEM_PROMPT = PROMPT_FILE.read_text(encoding="utf-8")
SEUIL_CONFIANCE = 0.7  # en dessous : revue humaine

log = logging.getLogger("docia")


def pdf_to_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def extract(path: Path) -> tuple[Extraction | None, dict]:
    """Extrait un document. Une relance si le JSON est invalide (étape Validation)."""
    text = pdf_to_text(path)
    trace = {"fichier": path.name, "prompt": PROMPT_VERSION, "modele": MODEL, "provider": PROVIDER,
             "appels": 0, "tokens_in": 0, "tokens_out": 0, "latence_s": 0.0, "cout_usd": 0.0}
    for _ in range(2):
        call = chat_json(SYSTEM_PROMPT, f"Document :\n<<<\n{text}\n>>>")
        trace["appels"] += 1
        trace["tokens_in"] += call.tokens_in
        trace["tokens_out"] += call.tokens_out
        trace["latence_s"] += call.latency_s
        trace["cout_usd"] += call.cost_usd
        try:
            result = Extraction.model_validate(json.loads(call.content))
            trace["json_valide"] = True
            return result, trace
        except (json.JSONDecodeError, ValidationError) as err:
            log.warning("JSON invalide pour %s : %s", path.name, err)
    trace["json_valide"] = False
    return None, trace


def process_dossier(folder: Path) -> dict:
    extractions, traces = {}, []
    for pdf in sorted(folder.glob("*.pdf")):
        result, trace = extract(pdf)
        traces.append(trace)
        if result:
            extractions[pdf.name] = result

    alerts = check_dossier(list(extractions.values()))
    confiance_min = min((e.confiance for e in extractions.values()), default=0.0)
    revue_humaine = bool(alerts) or confiance_min < SEUIL_CONFIANCE or len(extractions) < len(traces)
    return {
        "dossier": folder.name,
        "extractions": {k: v.model_dump() for k, v in extractions.items()},
        "alertes": alerts,
        "confiance_min": confiance_min,
        "revue_humaine": revue_humaine,
        "traces": traces,
    }
