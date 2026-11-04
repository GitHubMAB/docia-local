"""
Analyse un seul dossier et affiche le résultat, comme le verrait le conseiller.

Usage : python run.py samples/dossier_02_revenu_gonfle
"""

import json
import sys
from pathlib import Path

from docia.pipeline import process_dossier

if len(sys.argv) != 2:
    sys.exit("Usage : python run.py <dossier>")

result = process_dossier(Path(sys.argv[1]))
print(json.dumps(result, indent=2, ensure_ascii=False))
