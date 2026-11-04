"""
Contrôles de cohérence et de fraude, en Python pur (déterministes, testables, sans LLM).

Bonne pratique : le LLM extrait, le code décide. Les règles métier restent auditables.
"""
import re
import unicodedata

from docia.schema import Extraction

# Le revenu fiscal de référence ≈ salaires nets annuels après abattement de 10 %.
# On tolère un large écart (primes, mois incomplets) avant de lever une alerte.
RATIO_MIN, RATIO_MAX = 0.7, 1.3
TOLERANCE_VIREMENT = 1.0  # en euros


def normalize(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)  # virgules, tirets, points -> espaces
    return " ".join(sorted(text.upper().split()))  # ordre prénom / nom indifférent


def check_dossier(docs: list[Extraction]) -> list[dict]:
    alerts: list[dict] = []
    by_type = {d.type_document: d for d in docs}
    bulletin = by_type.get("bulletin_salaire")
    avis = by_type.get("avis_imposition")
    releve = by_type.get("releve_bancaire")

    names = {normalize(d.nom) for d in docs if d.nom}
    if len(names) > 1:
        alerts.append({"code": "NOM_DIFFERENT",
                       "detail": f"Noms différents selon les documents : {sorted(names)}"})

    if bulletin and avis and bulletin.salaire_net and avis.revenu_fiscal_reference:
        estime = bulletin.salaire_net * 12 * 0.9
        ratio = estime / avis.revenu_fiscal_reference
        if not RATIO_MIN <= ratio <= RATIO_MAX:
            alerts.append({"code": "REVENU_INCOHERENT",
                           "detail": f"Net annuel estimé {estime:.0f} € contre revenu fiscal "
                                     f"{avis.revenu_fiscal_reference:.0f} € (ratio {ratio:.2f})"})

    if bulletin and releve and bulletin.salaire_net and releve.virement_salaire:
        if abs(bulletin.salaire_net - releve.virement_salaire) > TOLERANCE_VIREMENT:
            alerts.append({"code": "VIREMENT_DIFFERENT",
                           "detail": f"Bulletin {bulletin.salaire_net:.2f} € contre virement "
                                     f"{releve.virement_salaire:.2f} €"})

    missing = {"bulletin_salaire", "avis_imposition", "releve_bancaire"} - by_type.keys()
    if missing:
        alerts.append({"code": "PIECE_MANQUANTE", "detail": f"Manque : {sorted(missing)}"})

    return alerts
