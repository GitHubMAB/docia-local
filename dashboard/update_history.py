"""
Ajoute le résumé d'un run (results/metrics.json) à l'historique publié sur GitHub Pages.

Usage : python dashboard/update_history.py results/metrics.json site/data/history.json
"""

import json
import sys
from pathlib import Path

MAX_RUNS = 500  # on garde les 500 derniers runs

metrics_path, history_path = Path(sys.argv[1]), Path(sys.argv[2])
if not metrics_path.exists():
    sys.exit(f"Pas de {metrics_path} : l'évaluation n'a pas produit de métriques, rien à publier.")

run = json.loads(metrics_path.read_text(encoding="utf-8"))
history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
history = [r for r in history if r.get("run_id") != run["run_id"]] + [run]  # pas de doublon si relance
history = sorted(history, key=lambda r: r["date"])[-MAX_RUNS:]

history_path.parent.mkdir(parents=True, exist_ok=True)
history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
print(f"Historique : {len(history)} runs")
