"""Schéma de sortie attendu du LLM, validé par Pydantic (étape « Validation » du cas pratique)."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Extraction(BaseModel):
    type_document: Literal["bulletin_salaire", "avis_imposition", "releve_bancaire", "autre"]
    nom: Optional[str] = None
    # Bulletin de salaire
    employeur: Optional[str] = None
    periode: Optional[str] = Field(None, description="AAAA-MM")
    salaire_brut: Optional[float] = None
    salaire_net: Optional[float] = None
    # Avis d'imposition
    annee_revenus: Optional[int] = None
    revenu_fiscal_reference: Optional[float] = None
    # Relevé bancaire
    mois: Optional[str] = Field(None, description="AAAA-MM")
    virement_salaire: Optional[float] = None
    solde_fin: Optional[float] = None
    # Auto-évaluation du modèle
    confiance: float = Field(1.0, ge=0, le=1)


CodeAlerte = Literal["NOM_DIFFERENT", "REVENU_INCOHERENT", "VIREMENT_DIFFERENT", "AVIS_ANCIEN", "PIECE_MANQUANTE"]


class AlerteLLM(BaseModel):
    code: CodeAlerte
    explication: str


class AnalyseLLM(BaseModel):
    """Verdict du LLM sur la cohérence d'un dossier complet."""
    coherent: bool
    alertes: List[AlerteLLM] = []
