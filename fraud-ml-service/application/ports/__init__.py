"""
HarisAI — Application Ports
═════════════════════════════════════════════════════════
Interfaces (contrats) que l'infrastructure doit respecter.

CONTENU :
─────────
  IFraudModel         → contrat pour tous les modèles ML
  IExplainableModel   → extension avec support SHAP
  IProfileStore       → contrat pour le stockage des profils Redis (expéditeur)
  IBeneficiaryStore   → contrat pour le stockage des profils bénéficiaires (destinataire)
  IExplainer          → contrat pour les explications SHAP
  IAuditStore         → contrat pour l'audit trail PostgreSQL

UTILISATION :
─────────────
  from application.ports import IFraudModel
  from application.ports import IProfileStore, IBeneficiaryStore
  from application.ports import IExplainer, IAuditStore

IMPLÉMENTATIONS (dans infrastructure/) :
─────────────────────────────────────────
  IFraudModel       ← XGBoostModel · IsolationForestModel · TFTModel · GNNModel
  IExplainableModel ← XGBoostModel (le seul qui supporte SHAP)
  IProfileStore     ← RedisProfileStore
  IBeneficiaryStore ← RedisBeneficiaryStore
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

from .i_beneficiary_store import (
    IBeneficiaryStore,
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
    "IBeneficiaryStore",

    # Explication + Audit
    "IExplainer",
    "IAuditStore",
]