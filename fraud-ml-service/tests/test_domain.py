"""
HarisAI — Tests unitaires Domain Layer
========================================
Teste les règles métier pures — sans Redis, PostgreSQL, ni XGBoost.
"""

import pytest
from datetime import datetime, timedelta

from domain import (
    Transaction, ClientProfile, FraudScore, Alert,
    Money, TokenHash, ShapReason,
    Currency, Channel, RiskLevel, FraudType,
    AlertStatus, AlertPriority,
)


# ═══════════════════════════════════════════════════
# MONEY
# ═══════════════════════════════════════════════════

class TestMoney:

    def test_creation_valide(self):
        m = Money(8500.0)
        assert m.amount == 8500.0
        assert m.currency == Currency.MRU

    def test_montant_negatif_interdit(self):
        with pytest.raises(ValueError):
            Money(-100.0)

    def test_montant_zero_autorise(self):
        m = Money(0.0)
        assert m.amount == 0.0

    def test_addition(self):
        m1 = Money(5000.0)
        m2 = Money(3000.0)
        assert (m1 + m2).amount == 8000.0

    def test_seuil_bcm(self):
        assert Money(9999.0).is_above_bcm_threshold() == False
        assert Money(10000.0).is_above_bcm_threshold() == True
        assert Money(47000.0).is_above_bcm_threshold() == True

    def test_ratio(self):
        montant  = Money(47000.0)
        moyenne  = Money(8500.0)
        ratio = montant.ratio_to(moyenne)
        assert round(ratio, 2) == 5.53

    def test_repr(self):
        assert "8,500.00 MRU" in repr(Money(8500.0))


# ═══════════════════════════════════════════════════
# TOKEN HASH
# ═══════════════════════════════════════════════════

class TestTokenHash:

    def test_creation_valide(self):
        t = TokenHash("a3f9b2c1d4e5f6a7")
        assert t.value == "a3f9b2c1d4e5f6a7"

    def test_token_trop_court(self):
        with pytest.raises(ValueError):
            TokenHash("abc")

    def test_short(self):
        t = TokenHash("a3f9b2c1d4e5f6a7")
        assert t.short() == "a3f9b2c1"

    def test_repr_anonymise(self):
        t = TokenHash("a3f9b2c1d4e5f6a7")
        assert "a3f9b2c1..." in repr(t)
        assert "d4e5f6a7" not in repr(t)


# ═══════════════════════════════════════════════════
# TRANSACTION
# ═══════════════════════════════════════════════════

class TestTransaction:

    def test_transaction_normale(self, tx_normale):
        assert tx_normale.hour_of_day == 9
        assert tx_normale.is_night_transaction == False
        assert tx_normale.is_weekend == False
        assert tx_normale.is_ussd_channel == False

    def test_transaction_nuit(self, tx_sim_swap):
        assert tx_sim_swap.hour_of_day == 2
        assert tx_sim_swap.is_night_transaction == True

    def test_sim_swap_detection(self, tx_sim_swap):
        assert tx_sim_swap.sim_changed_72h == True
        assert tx_sim_swap.device_id == "nouveau_device_inconnu"

    def test_transaction_id_obligatoire(self, client_token):
        with pytest.raises((ValueError, TypeError)):
            Transaction(
                transaction_id="",
                client_token=client_token,
                amount=Money(1000.0),
                timestamp=datetime.utcnow(),
                channel=Channel.MOBILE_APP,
                zone="TEVRAGH",
                operator="BANKILY",
                device_id="device_xyz",
            )


# ═══════════════════════════════════════════════════
# CLIENT PROFILE
# ═══════════════════════════════════════════════════

class TestClientProfile:

    def test_nouveau_device(self, client_profile):
        assert client_profile.is_new_device("nouveau_device") == True
        assert client_profile.is_new_device("device_habituel_xyz") == False

    def test_nouvelle_zone(self, client_profile):
        assert client_profile.is_new_zone("ROSSO") == True
        assert client_profile.is_new_zone("TEVRAGH_ZEINA") == False

    def test_z_score_normal(self, client_profile):
        z = client_profile.amount_z_score(8500.0)
        assert z == 0.0

    def test_z_score_suspect(self, client_profile):
        z = client_profile.amount_z_score(47000.0)
        assert z > 15  # Extrêmement anormal

    def test_compte_dormant(self, client_token):
        profile = ClientProfile(
            client_token=client_token,
            operator="BANKILY",
            last_transaction_at=datetime.utcnow() - timedelta(days=120),
        )
        assert profile.is_dormant_account() == True

    def test_compte_actif(self, client_profile):
        from datetime import datetime, timedelta
        client_profile.last_transaction_at = datetime.utcnow() - timedelta(days=2)
        assert client_profile.is_dormant_account() == False

    def test_nouveau_compte(self, client_token):
        profile = ClientProfile(
            client_token=client_token,
            operator="BANKILY",
            account_age_days=15,
        )
        assert profile.is_new_account() == True
        assert profile.is_new_account(days_threshold=10) == False


# ═══════════════════════════════════════════════════
# FRAUD SCORE
# ═══════════════════════════════════════════════════

class TestFraudScore:

    def test_compute_sim_swap(self, client_token):
        score = FraudScore.compute(
            transaction_id="BNK-001",
            client_token=client_token,
            xgboost_score=0.94,
            isolation_score=0.85,
            tft_score=0.88,
            gnn_score=0.72,
            shap_reasons=[],
            suspected_fraud_type=FraudType.SIM_SWAPPING,
            model_version="1.0.0",
        )
        assert score.risk_level == RiskLevel.BLOCK
        assert score.score_0_100 >= 70
        assert score.is_fraud == True

    def test_compute_normal(self, client_token):
        score = FraudScore.compute(
            transaction_id="BNK-002",
            client_token=client_token,
            xgboost_score=0.05,
            isolation_score=0.03,
            tft_score=0.02,
            gnn_score=0.01,
            shap_reasons=[],
            suspected_fraud_type=FraudType.UNKNOWN,
            model_version="1.0.0",
        )
        assert score.risk_level == RiskLevel.APPROVE
        assert score.is_approved == True

    def test_score_invalide(self, client_token):
        with pytest.raises(ValueError):
            FraudScore(
                transaction_id="BNK-003",
                client_token=client_token,
                final_score=1.5,  # > 1.0 → invalide
                risk_level=RiskLevel.BLOCK,
            )

    def test_top_reasons(self, client_token):
        reasons = [
            ShapReason("sim_changed_72h", 0.42, "SIM changée", "تغيير"),
            ShapReason("amount_z_score", 0.28, "Montant anormal", "مبلغ"),
            ShapReason("is_new_device", 0.31, "Nouveau device", "جهاز"),
            ShapReason("is_night", 0.15, "Transaction nuit", "ليل"),
        ]
        score = FraudScore.compute(
            transaction_id="BNK-004",
            client_token=client_token,
            xgboost_score=0.94,
            isolation_score=0.0,
            tft_score=0.0,
            gnn_score=0.0,
            shap_reasons=reasons,
            suspected_fraud_type=FraudType.SIM_SWAPPING,
            model_version="1.0.0",
        )
        top = score.top_reasons
        assert len(top) == 3
        assert top[0].feature_name == "sim_changed_72h"

    def test_poids_ensemble(self, client_token):
        """Vérifie que les poids XGBoost(40%) + IsoForest(20%) + TFT(25%) + GNN(15%) = 1.0."""
        from domain.fraud_score import (
            WEIGHT_XGBOOST, WEIGHT_ISOFOREST, WEIGHT_TFT, WEIGHT_GNN
        )
        total = WEIGHT_XGBOOST + WEIGHT_ISOFOREST + WEIGHT_TFT + WEIGHT_GNN
        assert abs(total - 1.0) < 0.001


# ═══════════════════════════════════════════════════
# ALERT
# ═══════════════════════════════════════════════════

class TestAlert:

    def _make_score(self, client_token, score=0.87):
        return FraudScore.compute(
            transaction_id="BNK-TEST",
            client_token=client_token,
            xgboost_score=score,
            isolation_score=0.0,
            tft_score=0.0,
            gnn_score=0.0,
            shap_reasons=[],
            suspected_fraud_type=FraudType.SIM_SWAPPING,
            model_version="1.0.0",
        )

    def test_alerte_pending(self, tx_sim_swap, client_token):
        score = self._make_score(client_token)
        alert = Alert(
            alert_id="ALT-001",
            transaction=tx_sim_swap,
            fraud_score=score,
        )
        assert alert.is_pending == True
        assert alert.status == AlertStatus.PENDING

    def test_priorite_critical(self, tx_sim_swap, client_token):
        # Score final élevé directement pour tester la priorité
        from domain import ShapReason
        score = FraudScore(
            transaction_id="BNK-CRIT",
            client_token=client_token,
            final_score=0.92,
            risk_level=RiskLevel.BLOCK,
            xgboost_score=0.94,
            isolation_score=0.0,
            tft_score=0.0,
            gnn_score=0.0,
            suspected_fraud_type=FraudType.SIM_SWAPPING,
            model_version="1.0.0",
        )
        alert = Alert(
            alert_id="ALT-002",
            transaction=tx_sim_swap,
            fraud_score=score,
        )
        assert alert.priority == AlertPriority.CRITICAL

    def test_confirmation_fraude(self, tx_sim_swap, client_token):
        score = self._make_score(client_token)
        alert = Alert(
            alert_id="ALT-003",
            transaction=tx_sim_swap,
            fraud_score=score,
        )
        alert.confirm_fraud("officer_hassan", "SIM swap confirmé")
        assert alert.is_confirmed_fraud == True
        assert alert.status == AlertStatus.CONFIRMED
        assert alert.reviewed_by == "officer_hassan"

    def test_faux_positif(self, tx_sim_swap, client_token):
        score = self._make_score(client_token)
        alert = Alert(
            alert_id="ALT-004",
            transaction=tx_sim_swap,
            fraud_score=score,
        )
        alert.mark_false_positive("officer_fatima", "Client vérifié")
        assert alert.is_false_positive == True
        assert alert.status == AlertStatus.FALSE_POSITIVE

    def test_double_traitement_interdit(self, tx_sim_swap, client_token):
        score = self._make_score(client_token)
        alert = Alert(
            alert_id="ALT-005",
            transaction=tx_sim_swap,
            fraud_score=score,
        )
        alert.confirm_fraud("officer_hassan")
        with pytest.raises(ValueError):
            alert.mark_false_positive("officer_fatima")

    def test_str_requis_pour_aml(self, tx_sim_swap, client_token):
        """STR BCM requis pour les fraudes AML confirmées."""
        score = FraudScore.compute(
            transaction_id="BNK-AML",
            client_token=client_token,
            xgboost_score=0.87,
            isolation_score=0.0,
            tft_score=0.0,
            gnn_score=0.0,
            shap_reasons=[],
            suspected_fraud_type=FraudType.STRUCTURING,
            model_version="1.0.0",
        )
        alert = Alert(
            alert_id="ALT-AML",
            transaction=tx_sim_swap,
            fraud_score=score,
        )
        alert.confirm_fraud("officer_hassan")
        assert alert.requires_str_report == True