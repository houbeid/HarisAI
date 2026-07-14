"""
HarisAI — Feature Engineering
================================
Transforme une Transaction brute + ClientProfile Redis (+ BeneficiaryProfile
Redis optionnel) en un dictionnaire de features numériques pour les 4 modèles ML.

DEUX TYPES DE FEATURES :
    22 features XGBoost  → FEATURE_NAMES → pour XGBoost + IsoForest
     7 features AML      → AML_FEATURE_NAMES → pour TFT + GNN

RÈGLE STRICTE :
    Les 22 features XGBoost doivent correspondre exactement
    à FEATURE_NAMES dans infrastructure/ml/models/xgboost_model.py

    Les 7 AML features sont supplémentaires — utilisées par TFT et GNN
    pour détecter les patterns multi-transactions (structuring, layering,
    comptes mules). is_mule_pattern est la seule des 7 à dépendre d'un
    second profil Redis — celui du BÉNÉFICIAIRE, pas du client — car
    détecter une mule nécessite de savoir ce que ce compte fait de
    l'argent qu'il REÇOIT, une information que ClientProfile seul
    (point de vue expéditeur) ne peut pas fournir.

FLUX :
    Transaction (webhook Bankily)
    + ClientProfile (Redis, côté expéditeur)
    + BeneficiaryProfile (Redis, côté destinataire — optionnel)
         ↓
    FeatureEngineering.compute()
         ↓
    Dict 22+7 = 29 features numériques
         ↓
    XGBoost → 22 features
    TFT     → 10 features temporelles + 7 AML
    GNN     → 8 features réseau + 7 AML
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from domain import ClientProfile, BeneficiaryProfile, Transaction
from infrastructure.ml.models.xgboost_model import FEATURE_NAMES

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CONSTANTES MÉTIER
# ─────────────────────────────────────────────

# Seuil BCM déclaratoire en MRU
# Transactions répétées juste en dessous = structuring (smurfing)
BCM_DECLARATION_THRESHOLD = 10_000.0

# Seuil z-score pour considérer un montant comme anormal
ZSCORE_ALERT_THRESHOLD = 3.0

# Compte considéré comme nouveau si moins de N jours
NEW_ACCOUNT_DAYS = 30

# Compte considéré comme dormant si inactif depuis N jours
DORMANT_ACCOUNT_DAYS = 90

# ─────────────────────────────────────────────
# AML FEATURES — patterns multi-transactions
# Utilisées par TFT et GNN uniquement
# ─────────────────────────────────────────────

AML_FEATURE_NAMES = [
    "tx_velocity_ratio",      # vitesse transactions vs habitude
    "amount_cumul_ratio",     # cumul 24h / moyenne mensuelle
    "near_threshold_flag",    # montant entre 8000-9999 MRU (structuring)
    "rapid_transfer_flag",    # retransfert rapide après réception
    "round_amount_flag",      # montants ronds suspects
    "many_beneficiaries_flag",# trop de bénéficiaires différents
    "is_mule_pattern",        # fan-in élevé + non-marchand + sortie rapide
]

# Zone de structuring — juste sous le seuil BCM
STRUCTURING_LOWER = BCM_DECLARATION_THRESHOLD * 0.90   # 9 000 MRU
STRUCTURING_UPPER = BCM_DECLARATION_THRESHOLD * 0.999  # 9 990 MRU

# Montants ronds suspects (en MRU)
ROUND_AMOUNTS = {
    5_000, 10_000, 15_000, 20_000,
    25_000, 50_000, 100_000, 200_000,
}


# ─────────────────────────────────────────────
# RÉSULTAT DU FEATURE ENGINEERING
# ─────────────────────────────────────────────

@dataclass
class FeatureSet:
    """
    Conteneur des features calculées.
    22 features XGBoost + 6 features AML = 28 total.
    """
    features: Dict[str, float]

    def to_dict(self) -> Dict[str, float]:
        return self.features

    def get(self, name: str, default: float = 0.0) -> float:
        return self.features.get(name, default)

    def xgboost_features(self) -> Dict[str, float]:
        """Retourne uniquement les 22 features pour XGBoost."""
        return {k: v for k, v in self.features.items() if k in FEATURE_NAMES}

    def aml_features(self) -> Dict[str, float]:
        """Retourne uniquement les 6 features AML pour TFT/GNN."""
        return {k: v for k, v in self.features.items() if k in AML_FEATURE_NAMES}

    def missing_features(self) -> list:
        """Retourne les features manquantes par rapport à FEATURE_NAMES."""
        return [f for f in FEATURE_NAMES if f not in self.features]

    def is_complete(self) -> bool:
        """True si toutes les 22 features XGBoost sont présentes."""
        return len(self.missing_features()) == 0

    def __repr__(self) -> str:
        top = sorted(
            self.features.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )[:5]
        return f"FeatureSet(top5={top})"


# ─────────────────────────────────────────────
# CLASSE PRINCIPALE
# ─────────────────────────────────────────────

class FeatureEngineering:
    """
    Calcule toutes les features pour les 4 modèles ML.

    Quatre catégories de features :
        1. Transaction    → directement depuis le webhook Bankily
        2. Comportement   → comparaison avec le profil Redis du client
        3. Ratios         → calculs dérivés
        4. AML            → patterns multi-transactions (TFT + GNN)

    Exemple :
        fe = FeatureEngineering()
        feature_set = fe.compute(transaction, profile)
        features = feature_set.to_dict()          # toutes les features
        xgb_feat = feature_set.xgboost_features() # 22 features XGBoost
        aml_feat = feature_set.aml_features()     # 6 features AML
    """

    def compute(
        self,
        transaction: Transaction,
        profile: ClientProfile,
        extra_features: Optional[Dict] = None,
        beneficiary_profile: Optional[BeneficiaryProfile] = None,
    ) -> FeatureSet:
        """
        Calcule les 22+6+1 features à partir de la transaction et du profil.

        Args:
            transaction          : transaction reçue de Bankily via webhook
            profile               : profil comportemental du client (expéditeur) depuis Redis
            extra_features        : features additionnelles pré-calculées par .NET
            beneficiary_profile   : profil comportemental du bénéficiaire (destinataire)
                                     depuis Redis — optionnel. Si absent, is_mule_pattern
                                     vaut 0.0 par défaut plutôt que de lever une erreur,
                                     pour ne pas casser les appels existants qui ne
                                     passent pas encore ce nouveau paramètre.

        Returns:
            FeatureSet contenant 22 features XGBoost + 7 features AML
        """
        features: Dict[str, float] = {}

        # Catégorie 1 — Features transaction (22 XGBoost)
        features.update(self._transaction_features(transaction))

        # Catégorie 2 — Features comportementales (22 XGBoost)
        features.update(self._behavioral_features(transaction, profile))

        # Catégorie 3 — Features ratios (22 XGBoost)
        features.update(self._ratio_features(transaction, profile))

        # Catégorie 4 — AML features (TFT + GNN uniquement)
        features.update(self._aml_features(transaction, profile))

        # Catégorie 5 — Compte mule (TFT + GNN uniquement)
        # Séparée de _aml_features() car elle dépend d'un profil différent
        # (bénéficiaire, pas client) — voir BeneficiaryProfile.is_likely_mule()
        features["is_mule_pattern"] = float(
            beneficiary_profile.is_likely_mule(
                is_merchant=transaction.beneficiary_is_merchant
            )
            if beneficiary_profile is not None
            else False
        )

        # Merge features additionnelles de .NET si présentes
        if extra_features:
            features.update(extra_features)

        feature_set = FeatureSet(features=features)

        # Vérification complétude des 22 features XGBoost
        missing = feature_set.missing_features()
        if missing:
            logger.warning(
                "Features manquantes — remplacées par 0",
                extra={
                    "transaction_id": transaction.transaction_id,
                    "missing": missing,
                }
            )
            for name in missing:
                features[name] = 0.0

        logger.debug(
            "Features calculées",
            extra={
                "transaction_id":  transaction.transaction_id,
                "amount_z_score":  round(features.get("amount_z_score", 0), 2),
                "is_new_device":   features.get("is_new_device", 0),
                "sim_changed_72h": features.get("sim_changed_72h", 0),
                "near_threshold":  features.get("near_threshold_flag", 0),
                "tx_velocity":     round(features.get("tx_velocity_ratio", 0), 2),
            }
        )

        return feature_set

    # ─────────────────────────────────────────
    # CATÉGORIE 1 — Features transaction
    # Directement depuis le webhook Bankily
    # ─────────────────────────────────────────

    def _transaction_features(
        self,
        tx: Transaction
    ) -> Dict[str, float]:
        """
        Features extraites directement de la transaction.
        Pas besoin du profil Redis — informations disponibles
        immédiatement depuis le webhook Bankily.
        """
        return {
            # Montant brut
            "amount": float(tx.amount.amount),

            # Temporel
            "hour_of_day":  float(tx.hour_of_day),
            "day_of_week":  float(tx.day_of_week),
            "is_night":     float(tx.is_night_transaction),
            "is_weekend":   float(tx.is_weekend),

            # Canal
            "is_ussd":  float(tx.is_ussd_channel),
            "is_agent": float(tx.is_agent_channel),

            # SIM — clé pour détecter SIM swapping
            "sim_changed_72h": float(tx.sim_changed_72h),

            # Bénéficiaire
            "beneficiary_is_merchant": float(
                tx.beneficiary_is_merchant
            ),
        }

    # ─────────────────────────────────────────
    # CATÉGORIE 2 — Features comportementales
    # Comparent la transaction avec le profil Redis
    # C'est ici que l'intelligence du système réside
    # ─────────────────────────────────────────

    def _behavioral_features(
        self,
        tx: Transaction,
        profile: ClientProfile,
    ) -> Dict[str, float]:
        """
        Features comportementales — comparent la transaction
        avec l'historique du client pour détecter les déviations.

        Ces features sont impossibles à calculer sans Redis.
        C'est la raison principale pour laquelle on stocke
        le profil de chaque client.
        """
        features = {}

        # ── Z-score du montant ────────────────
        # Mesure à combien d'écarts-types le montant actuel
        # est de la moyenne habituelle du client.
        # Z > 3  → anormal
        # Z > 10 → très suspect
        # Z > 19 → extrêmement suspect (comme dans notre exemple SIM swap)
        features["amount_z_score"] = float(
            profile.amount_z_score(tx.amount.amount)
        )

        # ── Nouveauté device ──────────────────
        # True si ce device n'a jamais été vu pour ce client.
        # Signal fort de SIM swapping — le fraudeur utilise son propre téléphone.
        features["is_new_device"] = float(
            profile.is_new_device(tx.device_id)
        )

        # ── Nouveauté zone géographique ───────
        # True si le client n'a jamais transacté depuis cette zone.
        features["is_new_zone"] = float(
            profile.is_new_zone(tx.zone)
        )

        # ── Heure inhabituelle ────────────────
        # True si le client ne transacte jamais à cette heure normalement.
        # Ex: client qui utilise Bankily seulement 8h-18h → transaction à 2h34
        features["is_unusual_hour"] = float(
            profile.is_unusual_hour(tx.hour_of_day)
        )

        # ── Canal inhabituel ──────────────────
        # True si le canal est inhabituel.
        # Ex: client qui utilise toujours l'app → soudainement USSD *888#
        features["is_unusual_channel"] = float(
            profile.is_unusual_channel(tx.channel)
        )

        # ── Compte dormant ────────────────────
        # True si le compte est inactif depuis 90+ jours.
        # Compte dormant réactivé = signal AML classique.
        features["is_dormant_account"] = float(
            profile.is_dormant_account(DORMANT_ACCOUNT_DAYS)
        )

        # ── Nouveau compte ────────────────────
        # True si le compte a moins de 30 jours.
        # Les comptes mules sont souvent créés récemment.
        features["is_new_account"] = float(
            profile.is_new_account(NEW_ACCOUNT_DAYS)
        )

        # ── Ancienneté et volume ──────────────
        features["account_age_days"]   = float(profile.account_age_days)
        features["total_transactions"] = float(profile.total_transactions)

        # ── Moyennes historiques ──────────────
        features["avg_amount_7d"]  = float(profile.avg_amount_7d)
        features["avg_amount_30d"] = float(profile.avg_amount_30d)

        # ── Nouveau bénéficiaire ──────────────
        # True si le client n'a jamais envoyé d'argent à ce destinataire.
        # Signal fort — les fraudeurs envoient toujours vers des comptes inconnus.
        if tx.beneficiary_token is not None:
            features["is_new_beneficiary"] = float(
                profile.is_new_beneficiary(tx.beneficiary_token)
            )
        else:
            features["is_new_beneficiary"] = 0.0

        return features

    # ─────────────────────────────────────────
    # CATÉGORIE 3 — Features ratios
    # Calculs dérivés combinant transaction et profil
    # ─────────────────────────────────────────

    def _ratio_features(
        self,
        tx: Transaction,
        profile: ClientProfile,
    ) -> Dict[str, float]:
        """
        Features dérivées calculées à partir des données brutes.
        Ces ratios donnent à XGBoost une perspective relative
        plutôt qu'absolue — plus robuste aux variations de montants.
        """
        features = {}

        # ── Ratio montant / moyenne 30 jours ─
        # Ex: 47000 / 8500 = 5.53
        # Signifie que ce montant est 5.5x la normale du client.
        # Plus interprétable que le z-score pour les humains.
        if profile.avg_amount_30d > 0:
            features["ratio_to_avg"] = float(
                tx.amount.amount / profile.avg_amount_30d
            )
        else:
            # Nouveau client sans historique → ratio = 1 par défaut
            features["ratio_to_avg"] = 1.0

        return features


    # ─────────────────────────────────────────
    # CATÉGORIE 4 — AML Features
    # Patterns multi-transactions pour TFT et GNN
    # Détectent structuring, layering, velocity
    # ─────────────────────────────────────────

    def _aml_features(
        self,
        tx: Transaction,
        profile: ClientProfile,
    ) -> Dict[str, float]:
        """
        Features AML — patterns sur plusieurs transactions.
        Utilisées par TFT et GNN uniquement.
        XGBoost n'utilise PAS ces features.
        """
        features = {}
        amount = tx.amount.amount

        # 1. Vélocité — rythme transactions vs habitude
        avg_tx_per_day = max(
            profile.total_transactions / max(profile.account_age_days, 1),
            0.1
        )
        recent_tx_estimate = min(profile.total_transactions, 10)
        features["tx_velocity_ratio"] = float(
            recent_tx_estimate / (avg_tx_per_day * 30 + 1)
        )

        # 2. Cumul 24h — structuring sur la journée
        monthly_avg = max(profile.avg_amount_30d, 1.0)
        estimated_daily_cumul = amount * max(recent_tx_estimate / 30, 1)
        features["amount_cumul_ratio"] = float(
            estimated_daily_cumul / (monthly_avg * 3 + 1)
        )

        # 3. Structuring — juste sous le seuil BCM 10 000 MRU
        features["near_threshold_flag"] = float(
            STRUCTURING_LOWER <= amount <= STRUCTURING_UPPER
        )

        # 4. Retransfert rapide — compte mule
        is_new_benef = bool(
            tx.beneficiary_token and
            profile.is_new_beneficiary(tx.beneficiary_token)
        )
        features["rapid_transfer_flag"] = float(
            is_new_benef and
            tx.is_night_transaction and
            amount > profile.avg_amount_30d * 2
        )

        # 5. Montants ronds suspects
        features["round_amount_flag"] = float(
            amount in ROUND_AMOUNTS or
            (amount >= 1000 and amount % 1000 == 0)
        )

        # 6. Trop de bénéficiaires différents
        known_beneficiaries = len(profile.known_beneficiary_tokens)
        features["many_beneficiaries_flag"] = float(
            known_beneficiaries > 20 and is_new_benef
        )

        return features


# ─────────────────────────────────────────────
# FONCTIONS UTILITAIRES
# ─────────────────────────────────────────────

def validate_features(features: Dict[str, float]) -> bool:
    """
    Vérifie que toutes les features requises sont présentes
    et que leurs valeurs sont valides.

    Args:
        features : dictionnaire de features à valider

    Returns:
        True si toutes les features sont présentes et valides

    Raises:
        ValueError si une feature critique est manquante
    """
    missing = [f for f in FEATURE_NAMES if f not in features]

    if missing:
        raise ValueError(
            f"Features manquantes pour XGBoost : {missing}\n"
            f"Features requises : {FEATURE_NAMES}"
        )

    # Vérifie les valeurs aberrantes
    for name, value in features.items():
        if not np.isfinite(value):
            raise ValueError(
                f"Feature '{name}' a une valeur invalide : {value}"
            )

    return True


def features_to_vector(features: Dict[str, float]) -> np.ndarray:
    """
    Convertit le dictionnaire de features en vecteur numpy.
    L'ordre respecte exactement FEATURE_NAMES.

    Args:
        features : dictionnaire des features calculées

    Returns:
        numpy array de shape (1, 22) — prêt pour XGBoost
    """
    vector = [
        float(features.get(name, 0.0))
        for name in FEATURE_NAMES
    ]
    return np.array(vector, dtype=np.float32).reshape(1, -1)


def log_suspicious_features(
    transaction_id: str,
    features: Dict[str, float],
) -> None:
    """
    Logue les features suspectes pour le débogage.
    Appelé seulement quand le score est élevé.
    """
    suspicious = []

    if features.get("sim_changed_72h", 0):
        suspicious.append("SIM changée dans les 72h")

    if features.get("is_new_device", 0):
        suspicious.append("Nouveau device")

    z = features.get("amount_z_score", 0)
    if z > ZSCORE_ALERT_THRESHOLD:
        suspicious.append(f"Montant anormal (z={z:.1f})")

    if features.get("is_new_zone", 0):
        suspicious.append("Nouvelle zone géographique")

    if features.get("is_dormant_account", 0):
        suspicious.append("Compte dormant réactivé")

    ratio = features.get("ratio_to_avg", 1)
    if ratio > 3:
        suspicious.append(f"Montant {ratio:.1f}x la moyenne")

    if suspicious:
        logger.warning(
            "Features suspectes détectées",
            extra={
                "transaction_id": transaction_id,
                "signals": suspicious,
            }
        )