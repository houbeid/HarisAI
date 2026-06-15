"""
HarisAI — Application Ports
═════════════════════════════════════════════════════════
Interfaces (contrats) que l'infrastructure doit respecter.

CONTENU :
─────────
  IFraudModel         → contrat pour tous les modèles ML
  IExplainableModel   → extension avec support SHAP
  IProfileStore       → contrat pour le stockage des profils Redis
  IExplainer          → contrat pour les explications SHAP
  IAuditStore         → contrat pour l'audit trail PostgreSQL

UTILISATION :
─────────────
  from application.ports import IFraudModel
  from application.ports import IProfileStore
  from application.ports import IExplainer, IAuditStore

IMPLÉMENTATIONS (dans infrastructure/) :
─────────────────────────────────────────
  IFraudModel       ← XGBoostModel · IsolationForestModel · TFTModel · GNNModel
  IExplainableModel ← XGBoostModel (le seul qui supporte SHAP)
  IProfileStore     ← RedisProfileStore
  IExplainer        ← ShapExplainer
  IAuditStore       ← PostgresAuditStore
"""

from .i_model import (
    IFraudModel,
    IExplainableModel,
)

from .i_profile_store import (
    IProfileStore,
)

from .i_explainer_audit import (
    IExplainer,
    IAuditStore,
)

__all__ = [
    # Modèles ML
    "IFraudModel",
    "IExplainableModel",

    # Stockage profils
    "IProfileStore",

    # Explication + Audit
    "IExplainer",
    "IAuditStore",
]