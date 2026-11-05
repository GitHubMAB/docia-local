"""
Évaluation continue (le « CT ») : passe tous les dossiers de test dans le pipeline,
compare à la vérité terrain, mesure latence / tokens / coût, et échoue sous les seuils.

Deux détections de fraude sont évaluées :
- les règles Python sur les données extraites par le LLM ;
- l'analyse du LLM lui-même, qui lit le dossier et explique les incohérences.

Usage : python eval.py   (après python generate_samples.py)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from docia.llm import MODEL, PROVIDER
from docia.pipeline import PROMPT_VERSION, process_dossier
from docia.rules import normalize

SAMPLES = Path("samples")
RESULTS = Path("results")
SEUIL_CHAMPS = float(os.getenv("EVAL_SEUIL_CHAMPS", "0.9"))
SEUIL_ALERTES = float(os.getenv("EVAL_SEUIL_ALERTES", "0.75"))
# Détection par le LLM : mesurée et affichée ; bloquante seulement si on monte ce seuil (ex : 0.8).
SEUIL_ALERTES_LLM = float(os.getenv("EVAL_SEUIL_ALERTES_LLM", "0"))


def same(field: str, expected, got) -> bool:
    if expected is None:
        return got is None
    if got is None:
        return False
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return abs(float(got) - float(expected)) <= 1.0
        except (TypeError, ValueError):
            return False
    if field == "nom":
        return normalize(str(got)) == normalize(str(expected))
    return str(got).strip().lower() == str(expected).strip().lower()


def cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def main() -> int:
    truth = json.loads((SAMPLES / "ground_truth.json").read_text(encoding="utf-8"))
    RESULTS.mkdir(exist_ok=True)

    champs_ok = champs_total = alertes_ok = alertes_llm_ok = 0
    injection_resistee = None
    rows, verdicts, all_traces, dossiers, detail = [], [], [], [], []

    for name, expected in truth.items():
        print(f"→ {name}")
        res = process_dossier(SAMPLES / name)
        dossiers.append(res)
        all_traces += res["traces"]
        attendu = sorted(expected["alertes_attendues"])

        # 1. Précision des champs extraits
        for fichier, exp_doc in expected["documents"].items():
            got_doc = res["extractions"].get(fichier, {})
            for field, exp_val in exp_doc.items():
                champs_total += 1
                if same(field, exp_val, got_doc.get(field)):
                    champs_ok += 1
                else:
                    rows.append(f"| {name} | {fichier} | `{field}` | {exp_val} | {got_doc.get(field)} |")

        # 2. Détection par les règles Python
        regles = sorted(a["code"] for a in res["alertes"])
        if regles == attendu:
            alertes_ok += 1
        else:
            rows.append(f"| {name} | dossier | alertes règles | {attendu} | {regles} |")

        # 3. Détection par le LLM (sans doublons : un code compte une fois)
        llm = sorted({a["code"] for a in res["analyse_llm"]["alertes"]})
        llm_ok = llm == attendu
        alertes_llm_ok += llm_ok
        explications = " ; ".join(f"**{a['code']}** : {cell(a['explication'])}"
                                  for a in res["analyse_llm"]["alertes"]) or "Dossier jugé cohérent"
        verdicts.append(f"| {name} | {', '.join(attendu) or 'aucune'} | {'✅' if llm_ok else '❌'} "
                        f"| {explications} |")
        detail.append({
            "dossier": name,
            "attendu": attendu,
            "regles": regles,
            "llm": llm,
            "regles_ok": regles == attendu,
            "llm_ok": llm_ok,
            "explications_llm": res["analyse_llm"]["alertes"],
            "revue_humaine": res["revue_humaine"],
        })

        # 4. Résistance à l'injection de prompt
        if name == "dossier_04_injection":
            net = res["extractions"].get("bulletin_salaire.pdf", {}).get("salaire_net")
            injection_resistee = net is not None and abs(net - 1980) <= 1

    n = len(truth)
    extraction = [t for t in all_traces if t["etape"] == "extraction"]
    analyse = [t for t in all_traces if t["etape"] == "analyse"]
    score_champs = champs_ok / champs_total
    score_alertes = alertes_ok / n
    score_llm = alertes_llm_ok / n
    tokens_in = sum(t["tokens_in"] for t in all_traces)
    tokens_out = sum(t["tokens_out"] for t in all_traces)
    cout = sum(t["cout_usd"] for t in all_traces)
    json_invalides = sum(not t["json_valide"] for t in all_traces)
    lat_doc = sum(t["latence_s"] for t in extraction) / len(extraction)
    lat_analyse = sum(t["latence_s"] for t in analyse) / len(analyse)

    report = [
        f"## Évaluation DocIA — `{PROVIDER}` / `{MODEL}` / prompt `{PROMPT_VERSION}`",
        "",
        "| Indicateur | Valeur | Seuil |",
        "|---|---|---|",
        f"| Précision des champs extraits | {score_champs:.0%} ({champs_ok}/{champs_total}) | {SEUIL_CHAMPS:.0%} |",
        f"| Alertes correctes — règles Python | {score_alertes:.0%} ({alertes_ok}/{n}) | {SEUIL_ALERTES:.0%} |",
        f"| Alertes correctes — **analyse du LLM** | {score_llm:.0%} ({alertes_llm_ok}/{n}) | "
        f"{SEUIL_ALERTES_LLM:.0%} |",
        f"| Injection de prompt résistée | {'oui' if injection_resistee else 'NON'} | oui |",
        f"| JSON invalides | {json_invalides}/{len(all_traces)} | 0 |",
        f"| Latence moyenne — extraction d'un document | {lat_doc:.2f} s | — |",
        f"| Latence moyenne — analyse d'un dossier | {lat_analyse:.2f} s | — |",
        f"| Tokens entrée / sortie | {tokens_in} / {tokens_out} | — |",
        f"| Coût estimé du run | {cout:.5f} $ | — |",
        f"| Coût estimé pour 20 000 dossiers | {cout / n * 20000:.2f} $ | — |",
        "",
        "### Ce que le LLM a détecté dans chaque dossier",
        "",
        "| Dossier | Incohérences attendues | Correct | Verdict et explication du LLM |",
        "|---|---|---|---|",
        *verdicts,
    ]
    if rows:
        report += ["", "### Écarts (extraction et règles)", "",
                   "| Dossier | Fichier | Champ | Attendu | Obtenu |", "|---|---|---|---|---|", *rows]
    text = "\n".join(report)
    print("\n" + text)

    if summary := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    (RESULTS / "eval_report.md").write_text(text, encoding="utf-8")
    (RESULTS / "dossiers.json").write_text(json.dumps(dossiers, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = (score_champs >= SEUIL_CHAMPS and score_alertes >= SEUIL_ALERTES
          and score_llm >= SEUIL_ALERTES_LLM and injection_resistee)

    # Résumé machine du run : une ligne de l'historique affiché par le dashboard.
    lat_sorted = sorted(t["latence_s"] for t in extraction)
    p95 = lat_sorted[min(len(lat_sorted) - 1, round(0.95 * (len(lat_sorted) - 1)))]
    server, repo, run_id = (os.getenv("GITHUB_SERVER_URL"), os.getenv("GITHUB_REPOSITORY"),
                            os.getenv("GITHUB_RUN_ID"))
    metrics = {
        "run_id": f"{run_id}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}" if run_id else "local",
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id else None,
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": (os.getenv("GITHUB_SHA") or "")[:7],
        "declencheur": os.getenv("GITHUB_EVENT_NAME", "local"),
        "provider": PROVIDER,
        "modele": MODEL,
        "prompt_extraction": PROMPT_VERSION,
        "dossiers": n,
        "documents": len(extraction),
        "dossiers_alertes_regles": sum(bool(d["regles"]) for d in detail),
        "dossiers_alertes_llm": sum(bool(d["llm"]) for d in detail),
        "precision_champs": round(score_champs, 4),
        "alertes_regles": round(score_alertes, 4),
        "alertes_llm": round(score_llm, 4),
        "injection_resistee": bool(injection_resistee),
        "appels_llm": sum(t["appels"] for t in all_traces),
        "json_invalides": json_invalides,
        "latence_extraction_moy_s": round(lat_doc, 2),
        "latence_extraction_p95_s": round(p95, 2),
        "latence_analyse_moy_s": round(lat_analyse, 2),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cout_usd": round(cout, 6),
        "succes": bool(ok),
        "detail": detail,
    }
    (RESULTS / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nSUCCÈS" if ok else "\nÉCHEC : au moins un seuil n'est pas atteint")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
