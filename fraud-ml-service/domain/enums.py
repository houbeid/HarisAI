"""
HarisAI — Domain Enums
=======================
Toutes les énumérations métier du système.
Ce fichier change uniquement quand on ajoute un nouveau type
(nouveau canal, nouvelle fraude, nouvelle décision).
"""

from enum import Enum


class Currency(str, Enum):
    """Devise supportée."""
    MRU = "MRU"  # Ouguiya mauritanien


class Channel(str, Enum):
    """Canal de la transaction mobile money."""
    MOBILE_APP = "MOBILE_APP"  # Application Bankily / Sedad
    USSD       = "USSD"        # *888# — téléphones basiques
    AGENT      = "AGENT"       # Agent physique terrain
    MERCHANT   = "MERCHANT"    # Paiement marchand
    ATM        = "ATM"         # Retrait guichet


class RiskLevel(str, Enum):
    """Décision finale du système pour chaque transaction."""
    APPROVE = "APPROVE"  # Transaction normale → passe
    REVIEW  = "REVIEW"   # Suspecte → compliance officer
    BLOCK   = "BLOCK"    # Fraude détectée → bloquée


class FraudType(str, Enum):
    """
    Type de fraude détectée.
    Utilisé dans les rapports STR envoyés à la BCM.

    STATUT DE DÉTECTION (revu suite à l'étude GSMA "Mobile Money Fraud
    Typologies and Mitigation Strategies", mars 2024, et à une description
    d'expert du secteur bancaire africain citée en conversation) :

        ACCOUNT_TAKEOVER et STRUCTURING ont une détection active dans
        _detect_fraud_type() — voir application/use_cases/
        analyze_transaction.py. MULE_ACCOUNT est relié à
        BeneficiaryProfile.is_likely_mule() (avec fallback sur
        l'ancienne heuristique brute si beneficiary_profile indisponible).

        REVERSAL_FRAUD, KYC_BREACH, OTP_THEFT : SANS détection active —
        voir commentaire par valeur. Ajoutées quand même dès maintenant
        (pas seulement quand la détection sera possible) car ce sont
        des catégories STR légitimes que la BCM peut demander de
        justifier, et étendre un enum utilisé dans un contrat figé
        (ScoreOut.fraud_type) coûte plus cher une fois .NET commencé.

        OTP_THEFT en particulier : contrairement à ACCOUNT_TAKEOVER
        (détectable avec is_new_device/is_new_zone/z-score déjà
        présents), rien dans les 22 features actuelles ni dans
        TransactionIn ne signale qu'un code OTP a été demandé ou
        utilisé récemment. Une règle basée sur les features existantes
        serait indiscernable d'ACCOUNT_TAKEOVER — un doublon déguisé,
        pas une vraie détection. Voir le document de proposition
        webhook Bankily pour le champ nécessaire (otp_requested_at /
        otp_verified_at).

        EXCLUES DÉLIBÉRÉMENT (pas juste "pas encore faites") :
        - COMMISSION_FRAUD / arbitrage agent (split transactions,
          topping-up) : nécessite une feature qui n'existe pas encore
          (comportement agent sur plusieurs transactions/tills) —
          à ajouter seulement quand cette feature sera conçue, pour
          éviter de répéter l'erreur trouvée sur is_mule_pattern
          (une valeur calculée mais jamais consommée par un modèle).
        - CICO_FRAUD (short-changing cash au guichet) : la différence
          entre cash physique remis et e-money crédité n'est PAS une
          donnée que HarisAI reçoit via le webhook transaction — c'est
          une réconciliation qui se passe hors du système. Hors scope
          structurel, pas juste une priorité basse.

        Ces exclusions/limites sont réversibles si une future revue du
        contrat webhook ou des données réelles Bankily change la donne.
    """
    # Fraudes mobile money spécifiques Mauritanie
    SIM_SWAPPING     = "SIM_SWAPPING"      # Clonage SIM — détection active
    OTP_THEFT        = "OTP_THEFT"         # Vol code OTP (négligence client,
                                            # OTP mal dirigé) — SANS détection
                                            # active, NÉCESSITE un champ absent
                                            # de TransactionIn (otp_requested_at/
                                            # otp_verified_at) pour se distinguer
                                            # d'ACCOUNT_TAKEOVER — voir docstring
                                            # ci-dessus
    USSD_SCAM        = "USSD_SCAM"         # Arnaque *888# — détection active
    FAKE_MERCHANT    = "FAKE_MERCHANT"     # Faux compte marchand — détection active
    FRAUDULENT_AGENT = "FRAUDULENT_AGENT"  # Agent Bankily frauduleux — détection active
    ACCOUNT_TAKEOVER = "ACCOUNT_TAKEOVER"  # Prise de contrôle SANS SIM swap
                                            # (is_new_device + is_new_zone + z-score
                                            # élevé, sans sim_changed_72h) —
                                            # détection active

    # Fraudes AML
    STRUCTURING      = "STRUCTURING"       # Smurfing sous seuil BCM — détection
                                            # active (montant proche du seuil +
                                            # tx_velocity_ratio élevé)
    LAYERING         = "LAYERING"          # Circulation entre comptes —
                                            # PAS de règle par choix : pattern
                                            # multi-comptes que _detect_fraud_type()
                                            # ne peut pas observer avec une seule
                                            # transaction + profil agrégé (voir
                                            # docstring de _detect_fraud_type())
    MULE_ACCOUNT     = "MULE_ACCOUNT"      # Compte mule blanchiment — détection
                                            # active via BeneficiaryProfile.
                                            # is_likely_mule(), fallback sur
                                            # l'ancienne heuristique brute si
                                            # beneficiary_profile indisponible

    # Fraudes identifiées via l'étude GSMA — sans détection active
    REVERSAL_FRAUD   = "REVERSAL_FRAUD"    # Reversal/chargeback abusif après
                                            # transaction légitime — NÉCESSITE un
                                            # champ absent de TransactionIn (type
                                            # d'événement) pour être détectable
    KYC_BREACH       = "KYC_BREACH"        # Dépôt direct / retrait à distance sans
                                            # présence physique vérifiée — NÉCESSITE
                                            # un champ absent de TransactionIn pour
                                            # être détectable

    # Fraudes générales
    UNUSUAL_BEHAVIOR = "UNUSUAL_BEHAVIOR"  # Comportement anormal
    UNKNOWN          = "UNKNOWN"           # Non classifié


class AlertPriority(str, Enum):
    """Priorité d'une alerte pour le tri dans le dashboard."""
    CRITICAL = "CRITICAL"  # Score >= 85
    HIGH     = "HIGH"      # Score >= 70
    MEDIUM   = "MEDIUM"    # Score >= 50
    LOW      = "LOW"       # Score < 50


class AlertStatus(str, Enum):
    """Statut du traitement d'une alerte par le compliance officer."""
    PENDING       = "PENDING"        # Pas encore traitée
    CONFIRMED     = "CONFIRMED"      # Fraude confirmée
    FALSE_POSITIVE = "FALSE_POSITIVE" # Faux positif