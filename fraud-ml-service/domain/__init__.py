"""
HarisAI — Domain Package
=========================
Point d'entrée unique pour tout le domain layer.

Le reste du projet importe toujours depuis `domain` directement :
    from domain import Transaction, FraudScore, RiskLevel

Jamais :
    from domain.transaction import Transaction  ← évite ça
    from domain.enums import RiskLevel          ← évite ça

Pourquoi ? Si on renomme un fichier interne, le reste du code
ne change pas — seulement cet __init__.py.
"""

from .enums import (
    Currency,
    Channel,
    RiskLevel,
    FraudType,
    AlertPriority,
    AlertStatus,
)

from .value_objects import (
    Money,
    TokenHash,
    ShapReason,
)

from .transaction import (
    Transaction,
    ClientProfile,
    BeneficiaryProfile,
)

from .fraud_score import (
    FraudScore,
    THRESHOLD_BLOCK,
    THRESHOLD_REVIEW,
    WEIGHT_XGBOOST,
    WEIGHT_ISOFOREST,
    WEIGHT_TFT,
    WEIGHT_GNN,
)

from .alert import (
    Alert,
)

__all__ = [
    # Enums
    "Currency",
    "Channel",
    "RiskLevel",
    "FraudType",
    "AlertPriority",
    "AlertStatus",

    # Value Objects
    "Money",
    "TokenHash",
    "ShapReason",

    # Entities
    "Transaction",
    "ClientProfile",
    "BeneficiaryProfile",
    "FraudScore",
    "Alert",

    # Constantes
    "THRESHOLD_BLOCK",
    "THRESHOLD_REVIEW",
    "WEIGHT_XGBOOST",
    "WEIGHT_ISOFOREST",
    "WEIGHT_TFT",
    "WEIGHT_GNN",
]