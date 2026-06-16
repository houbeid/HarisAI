"""
HarisAI — Schemas Pydantic
============================
Définit le contrat exact entre .NET et FastAPI.

.NET envoie → TransactionIn (JSON)
FastAPI retourne → ScoreOut (JSON)

Ces schemas sont la "traduction" entre le monde JSON de .NET
et les objets Python du domain layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────
# INPUT — ce que .NET envoie à FastAPI
# ─────────────────────────────────────────────

class TransactionIn(BaseModel):
    """
    Transaction reçue depuis .NET via webhook Bankily/Sedad.
    Tous les champs sont anonymisés — jamais de données personnelles.

    Exemple JSON reçu de .NET :
    {
        "transaction_id": "BNK-2024-001",
        "client_token": "a3f9b2c1d4e5f6a7...",
        "amount": 47000.0,
        "currency": "MRU",
        "channel": "MOBILE_APP",
        "zone": "ROSSO",
        "operator": "BANKILY",
        "device_id": "hash_device_xyz",
        "sim_changed_72h": true,
        "timestamp": "2024-01-15T02:34:00Z"
    }
    """

    # ── Identité ──────────────────────────────
    transaction_id:  str   = Field(..., description="ID unique de la transaction")
    client_token:    str   = Field(..., description="Hash SHA-256 du client — anonymisé")

    # ── Montant ───────────────────────────────
    amount:   float  = Field(..., gt=0, description="Montant en MRU")
    currency: str    = Field(default="MRU", description="Devise")

    # ── Canal et localisation ─────────────────
    channel:  str    = Field(..., description="MOBILE_APP · USSD · AGENT · MERCHANT")
    zone:     str    = Field(..., description="Zone géographique")
    operator: str    = Field(..., description="BANKILY · SEDAD · MASRVI")

    # ── Device et SIM ─────────────────────────
    device_id:          str   = Field(..., description="Hash du device")
    sim_changed_72h:    bool  = Field(default=False, description="SIM changée dans les 72h")
    sim_changed_at:     Optional[datetime] = Field(default=None)

    # ── Bénéficiaire ──────────────────────────
    beneficiary_token:       Optional[str]  = Field(default=None)
    beneficiary_is_merchant: bool           = Field(default=False)

    # ── Agent ─────────────────────────────────
    agent_id:     Optional[str] = Field(default=None)

    # ── USSD ──────────────────────────────────
    ussd_session: bool = Field(default=False)

    # ── Timestamp ─────────────────────────────
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # ── Features pré-calculées par .NET ───────
    # .NET peut pré-calculer certaines features pour réduire
    # la charge sur FastAPI — optionnel
    pre_computed_features: Optional[dict] = Field(default=None)

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v):
        allowed = {"BANKILY", "SEDAD", "MASRVI"}
        if v.upper() not in allowed:
            raise ValueError(f"Opérateur inconnu : {v}. Autorisés : {allowed}")
        return v.upper()

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v):
        allowed = {"MOBILE_APP", "USSD", "AGENT", "MERCHANT", "ATM"}
        if v.upper() not in allowed:
            raise ValueError(f"Canal inconnu : {v}. Autorisés : {allowed}")
        return v.upper()

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v):
        if v.upper() != "MRU":
            raise ValueError(f"Devise non supportée : {v}. Seul MRU est accepté.")
        return v.upper()

    model_config = {
        "json_schema_extra": {
            "example": {
                "transaction_id":  "BNK-2024-001",
                "client_token":    "a3f9b2c1d4e5f6a7b8c9d0e1f2a3b4c5",
                "amount":          47000.0,
                "currency":        "MRU",
                "channel":         "MOBILE_APP",
                "zone":            "ROSSO",
                "operator":        "BANKILY",
                "device_id":       "hash_device_nouveau_xyz",
                "sim_changed_72h": True,
                "beneficiary_token": "hash_destinataire_inconnu",
                "timestamp":       "2024-01-15T02:34:00Z"
            }
        }
    }


# ─────────────────────────────────────────────
# OUTPUT — ce que FastAPI retourne à .NET
# ─────────────────────────────────────────────

class ShapReasonOut(BaseModel):
    """Une raison SHAP dans la réponse."""
    feature_name:  str
    contribution:  float
    feature_value: float
    readable_fr:   str
    readable_ar:   str


class ScoreOut(BaseModel):
    """
    Réponse FastAPI vers .NET après analyse ML.

    Exemple JSON retourné à .NET :
    {
        "transaction_id": "BNK-2024-001",
        "score": 87,
        "decision": "BLOCK",
        "fraud_type": "SIM_SWAPPING",
        "alert_id": "ALT-C15FDD6C8FCB",
        "reasons": [...],
        "inference_time_ms": 87.5,
        "model_version": "1.0.0"
    }
    """

    # ── Identité ──────────────────────────────
    transaction_id: str

    # ── Score et décision ─────────────────────
    score:    int    = Field(..., ge=0, le=100, description="Score 0-100")
    decision: str    = Field(..., description="APPROVE · REVIEW · BLOCK")

    # ── Détails ───────────────────────────────
    fraud_type:  str
    alert_id:    Optional[str] = Field(default=None, description="Si REVIEW ou BLOCK")

    # ── Scores individuels des 4 modèles ──────
    xgboost_score:   float
    isolation_score: float
    tft_score:       float
    gnn_score:       float

    # ── Explication SHAP ──────────────────────
    reasons: List[ShapReasonOut] = Field(default_factory=list)

    # ── Méta ──────────────────────────────────
    inference_time_ms: float
    model_version:     str

    model_config = {
        "json_schema_extra": {
            "example": {
                "transaction_id":   "BNK-2024-001",
                "score":            87,
                "decision":         "BLOCK",
                "fraud_type":       "SIM_SWAPPING",
                "alert_id":         "ALT-C15FDD6C8FCB",
                "xgboost_score":    0.94,
                "isolation_score":  0.85,
                "tft_score":        0.88,
                "gnn_score":        0.72,
                "reasons": [
                    {
                        "feature_name":  "sim_changed_72h",
                        "contribution":  0.42,
                        "feature_value": 1.0,
                        "readable_fr":   "SIM changée il y a moins de 72h",
                        "readable_ar":   "تم تغيير الشريحة منذ أقل من 72 ساعة"
                    }
                ],
                "inference_time_ms": 87.5,
                "model_version":     "1.0.0"
            }
        }
    }


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

class HealthOut(BaseModel):
    """Réponse du health check — utilisé par .NET circuit breaker."""
    status:        str
    model_ready:   bool
    model_version: str
    uptime_seconds: float


class ErrorOut(BaseModel):
    """Réponse d'erreur standardisée."""
    error:   str
    detail:  Optional[str] = None
    code:    int