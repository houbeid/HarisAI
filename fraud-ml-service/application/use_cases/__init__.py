"""
HarisAI — Application Use Cases
═════════════════════════════════════════════════════════
Orchestrateurs du pipeline ML — la logique métier du système.

CONTENU :
─────────
  AnalyzeTransactionUseCase  → pipeline ML complet en 9 étapes
  AnalyzeTransactionInput    → ce qu'on envoie au use case (Transaction)
  AnalyzeTransactionOutput   → ce que le use case retourne (FraudScore + Alert)

UTILISATION :
─────────────
  from application.use_cases import AnalyzeTransactionUseCase
  from application.use_cases import AnalyzeTransactionInput
  from application.use_cases import AnalyzeTransactionOutput

FLUX :
──────
  routes.py (FastAPI)
      ↓ crée AnalyzeTransactionInput
  AnalyzeTransactionUseCase.execute()
      ↓ orchestre les 9 étapes
      1. Récupère profil client    → IProfileStore.get()
      2. Calcule les features
      3. Score XGBoost             → IExplainableModel.predict()
      4. Score Isolation Forest    → IFraudModel.predict()
      5. Score TFT                 → IFraudModel.predict()
      6. Score GNN                 → IFraudModel.predict()
      7. Explication SHAP          → IExplainer.explain()
      8. Score ensemble final      → FraudScore.compute()
      9. Audit trail               → IAuditStore.log_score()
      ↓ retourne AnalyzeTransactionOutput
  routes.py (FastAPI)
      ↓ sérialise en JSON
  .NET Backend
"""

from .analyze_transaction import (
    AnalyzeTransactionUseCase,
    AnalyzeTransactionInput,
    AnalyzeTransactionOutput,
)

__all__ = [
    "AnalyzeTransactionUseCase",
    "AnalyzeTransactionInput",
    "AnalyzeTransactionOutput",
]