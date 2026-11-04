"""Tests unitaires des règles métier : rapides, sans LLM, lancés à chaque PR."""

from docia.rules import check_dossier, normalize
from docia.schema import Extraction


def dossier(net=2450.0, rfr=26900.0, virement=2450.0, nom_avis="Camille MARTIN"):
    return [
        Extraction(type_document="bulletin_salaire", nom="Camille MARTIN", salaire_net=net),
        Extraction(type_document="avis_imposition", nom=nom_avis, revenu_fiscal_reference=rfr),
        Extraction(type_document="releve_bancaire", nom="Camille MARTIN", virement_salaire=virement),
    ]


def codes(alerts):
    return sorted(a["code"] for a in alerts)


def test_dossier_coherent_sans_alerte():
    assert check_dossier(dossier()) == []


def test_revenu_gonfle():
    assert "REVENU_INCOHERENT" in codes(check_dossier(dossier(net=4800, virement=4800)))


def test_virement_different():
    assert codes(check_dossier(dossier(virement=2300))) == ["VIREMENT_DIFFERENT"]


def test_nom_different():
    assert codes(check_dossier(dossier(nom_avis="Thomas DUBOIS"))) == ["NOM_DIFFERENT"]


def test_nom_normalise_accents_et_ordre():
    assert normalize("Hélène DURAND") == normalize("DURAND Helene")


def test_piece_manquante():
    assert codes(check_dossier(dossier()[:2])) == ["PIECE_MANQUANTE"]
