"""
HarisAI — Tests unitaires Domain Layer
========================================
Teste les règles métier pures — sans Redis, PostgreSQL, ni XGBoost.
"""

import pytest
from datetime import datetime, timedelta

from domain import (
    Transaction, ClientProfile, BeneficiaryProfile, FraudScore, Alert,
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

    def _make_score(self, client_token, xgb, iso, tft, gnn):
        return FraudScore.compute(
            transaction_id="BNK-OVERRIDE",
            client_token=client_token,
            xgboost_score=xgb,
            isolation_score=iso,
            tft_score=tft,
            gnn_score=gnn,
            shap_reasons=[],
            suspected_fraud_type=FraudType.UNKNOWN,
            model_version="1.0.0",
        )

    def test_override_gnn_seul_confiance_max_pas_noye(self, client_token):
        """
        Avant le mécanisme de dépassement : GNN seul à 1.0 donnait
        final_score=0.15 (1.0*WEIGHT_GNN), sous THRESHOLD_REVIEW (0.40)
        — un GNN certain à 100% d'une fraude n'aurait déclenché aucune
        revue humaine. C'est le cas concret qui a motivé ce mécanisme.
        """
        score = self._make_score(client_token, xgb=0.0, iso=0.0, tft=0.0, gnn=1.0)
        assert score.final_score < 0.40  # la moyenne pondérée seule reste basse
        assert score.risk_level == RiskLevel.REVIEW  # mais l'override corrige

    def test_override_tft_seul_confiance_max_pas_noye(self, client_token):
        score = self._make_score(client_token, xgb=0.0, iso=0.0, tft=1.0, gnn=0.0)
        assert score.risk_level == RiskLevel.REVIEW

    def test_override_xgboost_force_block(self, client_token):
        """XGBoost est le seul modèle assez mature pour forcer BLOCK seul."""
        score = self._make_score(client_token, xgb=0.95, iso=0.0, tft=0.0, gnn=0.0)
        assert score.risk_level == RiskLevel.BLOCK

    def test_override_gnn_ne_force_jamais_block(self, client_token):
        """
        Un modèle secondaire (IsoForest/TFT/GNN) très confiant force au
        maximum REVIEW, jamais BLOCK — ces modèles ne sont pas encore
        validés en production (voir chapitre 6 doc technique).
        """
        score = self._make_score(client_token, xgb=0.0, iso=0.0, tft=0.0, gnn=0.95)
        assert score.risk_level == RiskLevel.REVIEW
        assert score.risk_level != RiskLevel.BLOCK

    def test_override_ne_retrograde_jamais(self, client_token):
        """
        Si la moyenne pondérée donne déjà BLOCK, un override REVIEW
        (déclenché par un des 4 scores individuels) ne doit jamais
        rétrograder la décision à REVIEW.
        """
        score = self._make_score(client_token, xgb=0.9, iso=0.9, tft=0.9, gnn=0.95)
        assert score.risk_level == RiskLevel.BLOCK

    def test_override_n_affecte_pas_cas_normal(self, client_token):
        """Sans score extrême (>=0.90), le comportement est inchangé — pure moyenne pondérée."""
        score = self._make_score(client_token, xgb=0.3, iso=0.3, tft=0.3, gnn=0.3)
        assert score.risk_level == RiskLevel.APPROVE
        assert abs(score.final_score - 0.30) < 0.001


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


# ═══════════════════════════════════════════════════
# BENEFICIARY PROFILE — détection de comptes mules
# ═══════════════════════════════════════════════════

class TestBeneficiaryProfile:
    """
    BeneficiaryProfile suit le compte qui REÇOIT l'argent, symétrique
    à ClientProfile qui suit celui qui ENVOIE. Nécessaire pour distinguer
    un compte mule d'un marchand légitime (supermarché, boutique,
    restaurant) qui reçoit lui aussi de très nombreux clients différents
    chaque jour — un fan-in élevé seul ne suffit jamais à conclure.
    """

    def _make_token(self, prefix: str) -> TokenHash:
        return TokenHash((prefix * 64)[:64])

    def test_nouveau_beneficiaire_sans_historique(self):
        """Un compte qui n'a encore rien reçu n'est jamais flaggé mule."""
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
        )
        assert profile.fan_in_ratio() == 0.0
        assert profile.has_high_fan_in() is False
        assert profile.is_likely_mule(is_merchant=False) is False

    def test_is_new_sender(self):
        """Détecte si un expéditeur est nouveau pour ce bénéficiaire."""
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            known_sender_tokens=["x" * 64],
        )
        assert profile.is_new_sender(TokenHash("y" * 64)) is True
        assert profile.is_new_sender(TokenHash("x" * 64)) is False

    def test_fan_in_ratio_mule_typique(self):
        """
        Une mule a un fan_in_ratio proche de 1.0 — presque chaque
        transaction reçue vient d'un expéditeur différent, contrairement
        à un marchand dont les clients reviennent régulièrement.
        """
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            distinct_senders_30d=25,
            total_transactions_received=27,
        )
        assert profile.fan_in_ratio() == pytest.approx(25 / 27, rel=1e-3)

    def test_outflow_speed_apres_reception(self):
        """Mesure le délai entre réception et sortie de fonds suivante."""
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            last_received_at=datetime(2026, 6, 18, 10, 0),
            last_outflow_at=datetime(2026, 6, 18, 14, 0),
        )
        assert profile.outflow_speed_hours() == pytest.approx(4.0)

    def test_outflow_speed_aucune_sortie_encore(self):
        """Sans sortie de fonds après réception, le délai est None."""
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            last_received_at=datetime(2026, 6, 18, 10, 0),
            last_outflow_at=None,
        )
        assert profile.outflow_speed_hours() is None

    def test_outflow_speed_sortie_anterieure_a_reception(self):
        """
        Si la dernière sortie est ANTÉRIEURE à la dernière réception
        (l'argent reçu n'est pas encore reparti), pas de délai mesurable.
        """
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            last_received_at=datetime(2026, 6, 18, 14, 0),
            last_outflow_at=datetime(2026, 6, 18, 10, 0),  # avant
        )
        assert profile.outflow_speed_hours() is None

    def test_mule_detectee_fan_in_eleve_non_marchand_sortie_rapide(self):
        """
        Cas central — combine les trois conditions du pattern mule :
        fan-in élevé, pas marchand, sortie rapide après réception.
        Doit être détectée comme suspecte.
        """
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            distinct_senders_30d=25,
            total_transactions_received=27,
            last_received_at=datetime(2026, 6, 18, 10, 0),
            last_outflow_at=datetime(2026, 6, 18, 13, 0),  # 3h après
        )
        assert profile.is_likely_mule(is_merchant=False) is True

    def test_marchand_legitime_jamais_flagge_meme_fan_in_tres_eleve(self):
        """
        Cas critique pour le contexte mauritanien — un supermarché,
        une boutique ou un restaurant affilié à Bankily/Sedad reçoit
        légitimement des centaines de clients différents chaque jour.
        is_merchant=True doit exclure ce compte d'office, quel que
        soit son fan-in.
        """
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            distinct_senders_30d=300,  # fan-in énorme, supermarché actif
            total_transactions_received=320,
            last_received_at=datetime(2026, 6, 18, 18, 0),
            last_outflow_at=datetime(2026, 6, 18, 19, 0),  # sort vite aussi (fournisseurs)
        )
        assert profile.is_likely_mule(is_merchant=True) is False

    def test_marchand_non_declare_mais_garde_ses_fonds_pas_flagge(self):
        """
        Filet de sécurité supplémentaire — même si beneficiary_is_merchant
        est mal renseigné (False par erreur) pour un commerce légitime,
        l'absence de sortie rapide (le commerce garde son chiffre
        d'affaires au lieu de le faire transiter) empêche le flag.
        """
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            distinct_senders_30d=300,
            total_transactions_received=320,
            last_received_at=datetime(2026, 6, 18, 18, 0),
            last_outflow_at=datetime(2026, 5, 1, 9, 0),  # vieille sortie, pas liée
        )
        assert profile.is_likely_mule(is_merchant=False) is False

    def test_fan_in_faible_jamais_flagge_meme_sortie_rapide(self):
        """
        Un compte qui reçoit de très peu de sources différentes mais
        fait sortir l'argent vite n'est pas un profil mule typique
        (ex: un client qui reçoit un remboursement puis paie une facture).
        Le fan-in élevé est une condition nécessaire, pas accessoire.
        """
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            distinct_senders_30d=2,
            total_transactions_received=2,
            last_received_at=datetime(2026, 6, 18, 10, 0),
            last_outflow_at=datetime(2026, 6, 18, 10, 30),
        )
        assert profile.is_likely_mule(is_merchant=False) is False

    def test_sortie_trop_lente_jamais_flaggee(self):
        """
        Fan-in élevé et non-marchand, mais la sortie de fonds survient
        plusieurs jours après réception — pas le pattern mule typique
        de transit rapide, ne doit pas être flaggé par défaut (24h).
        """
        profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("a"),
            operator="BANKILY",
            distinct_senders_30d=20,
            total_transactions_received=22,
            last_received_at=datetime(2026, 6, 10, 10, 0),
            last_outflow_at=datetime(2026, 6, 18, 10, 0),  # 8 jours après
        )
        assert profile.is_likely_mule(is_merchant=False) is False


# ═══════════════════════════════════════════════════
# FEATURE ENGINEERING — is_mule_pattern
# ═══════════════════════════════════════════════════

class TestIsMulePatternFeature:
    """
    Vérifie l'intégration de is_mule_pattern dans FeatureEngineering —
    la 7e feature AML, qui dépend de BeneficiaryProfile en plus de
    ClientProfile (contrairement aux 6 autres features AML).
    """

    def _make_token(self, prefix: str) -> TokenHash:
        return TokenHash((prefix * 64)[:64])

    def test_sans_beneficiary_profile_vaut_zero(self, tx_normale, client_profile):
        """
        Compatibilité ascendante — les appels existants qui ne passent
        pas beneficiary_profile ne doivent pas casser, et la feature
        vaut 0.0 par défaut plutôt que de lever une erreur.
        """
        from infrastructure.ml.features.feature_engineering import (
            FeatureEngineering, AML_FEATURE_NAMES,
        )
        fe = FeatureEngineering()
        feature_set = fe.compute(tx_normale, client_profile)
        assert feature_set.get("is_mule_pattern") == 0.0
        assert "is_mule_pattern" in AML_FEATURE_NAMES

    def test_avec_profil_mule_la_feature_vaut_un(self, tx_normale, client_profile):
        """Un profil bénéficiaire mule fait passer la feature à 1.0."""
        from infrastructure.ml.features.feature_engineering import FeatureEngineering

        mule_profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("b"),
            operator="BANKILY",
            distinct_senders_30d=25,
            total_transactions_received=27,
            last_received_at=datetime(2026, 6, 18, 10, 0),
            last_outflow_at=datetime(2026, 6, 18, 13, 0),
        )
        fe = FeatureEngineering()
        feature_set = fe.compute(
            tx_normale, client_profile, beneficiary_profile=mule_profile
        )
        assert feature_set.get("is_mule_pattern") == 1.0

    def test_avec_profil_marchand_la_feature_vaut_zero(self, client_token):
        """
        Un marchand légitime avec fan-in élevé ne doit jamais faire
        passer is_mule_pattern à 1.0, même avec beaucoup d'expéditeurs.
        """
        from infrastructure.ml.features.feature_engineering import FeatureEngineering

        tx_merchant = Transaction(
            transaction_id="TX-MERCHANT",
            client_token=client_token,
            amount=Money(5000.0),
            timestamp=datetime(2026, 6, 18, 14, 0),
            channel=Channel.MOBILE_APP,
            zone="NOUAKCHOTT",
            operator="BANKILY",
            device_id="dev1",
            beneficiary_token=self._make_token("c"),
            beneficiary_is_merchant=True,
        )
        merchant_profile = BeneficiaryProfile(
            beneficiary_token=self._make_token("c"),
            operator="BANKILY",
            distinct_senders_30d=300,
            total_transactions_received=320,
            last_received_at=datetime(2026, 6, 18, 18, 0),
            last_outflow_at=datetime(2026, 6, 18, 19, 0),
        )
        fe = FeatureEngineering()
        client_profile = ClientProfile(client_token=client_token, operator="BANKILY")
        feature_set = fe.compute(
            tx_merchant, client_profile, beneficiary_profile=merchant_profile
        )
        assert feature_set.get("is_mule_pattern") == 0.0

    def test_is_mule_pattern_dans_aml_features(self, tx_normale, client_profile):
        """is_mule_pattern doit apparaître dans aml_features(), pas xgboost_features()."""
        from infrastructure.ml.features.feature_engineering import FeatureEngineering

        fe = FeatureEngineering()
        feature_set = fe.compute(tx_normale, client_profile)
        assert "is_mule_pattern" in feature_set.aml_features()
        assert "is_mule_pattern" not in feature_set.xgboost_features()