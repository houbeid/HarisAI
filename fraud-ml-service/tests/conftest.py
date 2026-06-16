"""
HarisAI — conftest.py
======================
Configuration pytest et fixtures partagées entre tous les tests.

Les fixtures définies ici sont disponibles dans tous les fichiers de test
sans import explicite — pytest les injecte automatiquement.
"""

import asyncio
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from domain import (
    Transaction, ClientProfile, FraudScore, Alert,
    Money, TokenHash, Channel, RiskLevel, FraudType,
    ShapReason,
)
from application.ports import (
    IFraudModel, IExplainableModel,
    IProfileStore, IExplainer, IAuditStore,
)
from application.use_cases import (
    AnalyzeTransactionUseCase,
    AnalyzeTransactionInput,
)
from infrastructure.stores import (
    InMemoryProfileStore,
    InMemoryAuditStore,
    InMemoryPredictionCache,
    InMemoryTransactionQueue,
)
from infrastructure.ml.explainer.shap_explainer import ShapExplainer


# ─────────────────────────────────────────────
# CONFIGURATION PYTEST
# ─────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: tests d'intégration bout-en-bout"
    )
    config.addinivalue_line(
        "markers",
        "unit: tests unitaires"
    )


# ─────────────────────────────────────────────
# MOCKS RÉUTILISABLES
# ─────────────────────────────────────────────

class MockXGBoostModel(IExplainableModel):
    """Mock XGBoost qui simule les vrais scores de fraude."""

    def __init__(self, fraud_score: float = 0.05):
        self._fraud_score = fraud_score

    @property
    def model_name(self) -> str:
        return "xgboost_fraud"

    @property
    def model_version(self) -> str:
        return "1.0.0-test"

    async def is_ready(self) -> bool:
        return True

    async def load(self, path: str) -> None:
        pass

    async def predict(self, tx, profile, features) -> float:
        """
        Retourne un score suffisamment élevé pour déclencher BLOCK/REVIEW.
        Note : le score final = XGBoost*0.40 + autres*0.60
        Pour BLOCK (>=0.70) avec XGBoost seul on retourne 1.0 → 1.0*0.40=0.40 (REVIEW)
        Pour forcer BLOCK on retourne 1.0 et tous les autres modèles aussi 1.0
        → 1.0*0.40 + 1.0*0.20 + 1.0*0.25 + 1.0*0.15 = 1.0 → BLOCK
        """
        if features.get("sim_changed_72h") and features.get("is_new_device"):
            return 1.0   # SIM swap → tous les modèles retournent 1.0 → BLOCK
        if features.get("is_dormant_account"):
            return 1.0   # Compte dormant → BLOCK
        if features.get("amount_z_score", 0) > 10:
            return 0.80  # Montant très anormal → REVIEW/BLOCK
        return self._fraud_score  # Normal → APPROVE

    def get_feature_importance(self) -> dict:
        from infrastructure.ml.models.xgboost_model import FEATURE_NAMES
        return {name: 0.01 for name in FEATURE_NAMES}

    async def explain(self, tx, profile, features) -> list:
        return [
            {
                "feature_name":  "sim_changed_72h",
                "contribution":  0.42,
                "feature_value": features.get("sim_changed_72h", 0),
                "readable_fr":   "SIM changée il y a moins de 72h",
                "readable_ar":   "تم تغيير الشريحة منذ أقل من 72 ساعة",
            },
            {
                "feature_name":  "amount_z_score",
                "contribution":  0.28,
                "feature_value": features.get("amount_z_score", 0),
                "readable_fr":   "Montant anormal",
                "readable_ar":   "مبلغ غير طبيعي",
            },
        ]


class MockPassThroughModel(IFraudModel):
    """
    Mock modèle qui suit le signal XGBoost.
    Retourne 1.0 pour SIM swap (pour que le score ensemble dépasse 0.70).
    """

    def __init__(self, name: str):
        self._name = name

    @property
    def model_name(self) -> str:
        return self._name

    @property
    def model_version(self) -> str:
        return "placeholder"

    async def is_ready(self) -> bool:
        return True

    async def load(self, path: str) -> None:
        pass

    async def predict(self, tx, profile, features) -> float:
        # Suit XGBoost uniquement pour les fraudes claires
        if tx.sim_changed_72h and features.get("is_new_device"):
            return 1.0
        if features.get("is_dormant_account"):
            return 1.0
        return 0.0


class MockExplainer(IExplainer):
    """Mock SHAP explainer."""

    async def explain(self, transaction, profile, features, raw_score) -> list:
        return [
            {
                "feature_name":  "sim_changed_72h",
                "contribution":  0.42 if features.get("sim_changed_72h") else -0.1,
                "feature_value": features.get("sim_changed_72h", 0),
                "readable_fr":   "SIM changée il y a moins de 72h",
                "readable_ar":   "تم تغيير الشريحة منذ أقل من 72 ساعة",
            }
        ]

    async def is_ready(self) -> bool:
        return True


# ─────────────────────────────────────────────
# FIXTURES — données de test
# ─────────────────────────────────────────────

@pytest.fixture
def client_token() -> TokenHash:
    return TokenHash("a3f9b2c1d4e5f6a7")


@pytest.fixture
def client_profile(client_token) -> ClientProfile:
    """Profil client avec historique normal."""
    return ClientProfile(
        client_token=client_token,
        operator="BANKILY",
        avg_amount_7d=8500.0,
        avg_amount_30d=8500.0,
        std_amount_7d=2000.0,
        usual_zones=["TEVRAGH_ZEINA", "KSAR"],
        usual_channels=["MOBILE_APP"],
        known_device_ids=["device_habituel_xyz"],
        usual_hours=[8, 9, 10, 17, 18],
        known_beneficiary_tokens=["ami_hash_abc"],
        total_transactions=145,
        account_age_days=365,
        last_transaction_at=datetime.now(timezone.utc) - timedelta(days=2),
    )


@pytest.fixture
def tx_normale(client_token) -> Transaction:
    """Transaction mobile money normale."""
    return Transaction(
        transaction_id="BNK-TEST-001",
        client_token=client_token,
        amount=Money(8500.0),
        timestamp=datetime(2024, 1, 15, 9, 30),
        channel=Channel.MOBILE_APP,
        zone="TEVRAGH_ZEINA",
        operator="BANKILY",
        device_id="device_habituel_xyz",
    )


@pytest.fixture
def tx_sim_swap(client_token) -> Transaction:
    """Transaction SIM swap — fraude mobile money #1."""
    return Transaction(
        transaction_id="BNK-TEST-002",
        client_token=client_token,
        amount=Money(47000.0),
        timestamp=datetime(2024, 1, 15, 2, 34),
        channel=Channel.MOBILE_APP,
        zone="ROSSO",
        operator="BANKILY",
        device_id="nouveau_device_inconnu",
        sim_changed_72h=True,
        beneficiary_token=TokenHash("destinataire_jamais_vu0"),
    )


@pytest.fixture
def tx_structuring(client_token) -> Transaction:
    """Transaction smurfing — juste sous le seuil BCM."""
    return Transaction(
        transaction_id="BNK-TEST-003",
        client_token=client_token,
        amount=Money(9800.0),  # Juste sous le seuil BCM 10 000
        timestamp=datetime(2024, 1, 15, 14, 0),
        channel=Channel.MOBILE_APP,
        zone="TEVRAGH_ZEINA",
        operator="BANKILY",
        device_id="device_habituel_xyz",
    )


@pytest.fixture
def tx_dormant(client_token) -> Transaction:
    """Compte dormant réactivé — signal AML."""
    return Transaction(
        transaction_id="BNK-TEST-004",
        client_token=TokenHash("dormant_client_hash0"),
        amount=Money(85000.0),
        timestamp=datetime(2024, 1, 15, 14, 0),
        channel=Channel.MOBILE_APP,
        zone="TEVRAGH_ZEINA",
        operator="BANKILY",
        device_id="device_dormant_xyz",
    )


# ─────────────────────────────────────────────
# FIXTURES — stores et use case
# ─────────────────────────────────────────────

@pytest.fixture
def profile_store(client_profile) -> InMemoryProfileStore:
    """Store avec un profil client pré-chargé."""
    store = InMemoryProfileStore()
    store.seed(client_profile.client_token, "BANKILY", client_profile)
    return store


@pytest.fixture
def audit_store() -> InMemoryAuditStore:
    return InMemoryAuditStore()


@pytest.fixture
def prediction_cache() -> InMemoryPredictionCache:
    return InMemoryPredictionCache()


@pytest.fixture
def transaction_queue() -> InMemoryTransactionQueue:
    return InMemoryTransactionQueue()


@pytest.fixture
def use_case(profile_store, audit_store) -> AnalyzeTransactionUseCase:
    """Use case configuré avec tous les mocks."""
    return AnalyzeTransactionUseCase(
        xgboost_model=MockXGBoostModel(),
        isolation_model=MockPassThroughModel("isolation_forest"),
        tft_model=MockPassThroughModel("tft_aml"),
        gnn_model=MockPassThroughModel("gnn_network"),
        profile_store=profile_store,
        explainer=MockExplainer(),
        audit_store=audit_store,
    )


# ─────────────────────────────────────────────
# FIXTURES — application FastAPI
# ─────────────────────────────────────────────

@pytest.fixture
def test_app(use_case, prediction_cache, transaction_queue) -> FastAPI:
    """
    Application FastAPI configurée pour les tests.
    Utilise les mocks au lieu des vrais Redis/PostgreSQL/XGBoost.
    """
    from main import app
    from infrastructure.ml.models.xgboost_model import XGBoostModel

    # Injecte les mocks dans l'état de l'app
    app.state.use_case          = use_case
    app.state.prediction_cache  = prediction_cache
    app.state.transaction_queue = transaction_queue
    app.state.xgboost_model     = MockXGBoostModel()
    app.state.start_time        = 0.0

    return app


@pytest_asyncio.fixture
async def client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """
    Client HTTP pour tester les endpoints FastAPI.
    Utilise httpx avec ASGI transport — pas de vrai serveur HTTP.
    """
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
        headers={"X-Api-Key": "harisai-secret-key-change-in-production"},
    ) as ac:
        yield ac


# ─────────────────────────────────────────────
# DONNÉES JSON — pour les tests API
# ─────────────────────────────────────────────

@pytest.fixture
def tx_normale_json() -> dict:
    """JSON d'une transaction normale — envoyé par .NET."""
    return {
        "transaction_id":  "BNK-API-001",
        "client_token":    "a3f9b2c1d4e5f6a7",
        "amount":          8500.0,
        "currency":        "MRU",
        "channel":         "MOBILE_APP",
        "zone":            "TEVRAGH_ZEINA",
        "operator":        "BANKILY",
        "device_id":       "device_habituel_xyz",
        "sim_changed_72h": False,
        "timestamp":       "2024-01-15T09:30:00",
    }


@pytest.fixture
def tx_sim_swap_json() -> dict:
    """JSON d'une transaction SIM swap — envoyé par .NET."""
    return {
        "transaction_id":   "BNK-API-002",
        "client_token":     "a3f9b2c1d4e5f6a7",
        "amount":           47000.0,
        "currency":         "MRU",
        "channel":          "MOBILE_APP",
        "zone":             "ROSSO",
        "operator":         "BANKILY",
        "device_id":        "nouveau_device_inconnu",
        "sim_changed_72h":  True,
        "beneficiary_token": "destinataire_jamais_vu0",
        "timestamp":        "2024-01-15T02:34:00",
    }