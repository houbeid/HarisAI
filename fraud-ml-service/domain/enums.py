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
    Typologies and Mitigation Strategies", mars 2024) :

        ACCOUNT_TAKEOVER, REVERSAL_FRAUD, KYC_BREACH : ajoutées mais
        SANS détection active pour l'instant — voir commentaire par
        valeur. Ajoutées maintenant plutôt que plus tard car ce sont
        des catégories STR légitimes que la BCM peut demander de
        justifier, et étendre un enum utilisé dans un contrat figé
        (ScoreOut.fraud_type) coûte plus cher une fois .NET commencé.

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

        Ces deux exclusions sont réversibles si une future revue du
        contrat webhook ou des données réelles Bankily change la donne.
    """
    # Fraudes mobile money spécifiques Mauritanie
    SIM_SWAPPING     = "SIM_SWAPPING"      # Clonage SIM — détection active
    OTP_THEFT        = "OTP_THEFT"         # Vol code OTP
    USSD_SCAM        = "USSD_SCAM"         # Arnaque *888# — détection active
    FAKE_MERCHANT    = "FAKE_MERCHANT"     # Faux compte marchand — détection active
    FRAUDULENT_AGENT = "FRAUDULENT_AGENT"  # Agent Bankily frauduleux — détection active
    ACCOUNT_TAKEOVER = "ACCOUNT_TAKEOVER"  # Prise de contrôle SANS SIM swap
                                            # (is_new_device + is_new_zone + z-score
                                            # élevé, sans sim_changed_72h) — PAS ENCORE
                                            # branché dans _detect_fraud_type()

    # Fraudes AML
    STRUCTURING      = "STRUCTURING"       # Smurfing sous seuil BCM
    LAYERING         = "LAYERING"          # Circulation entre comptes
    MULE_ACCOUNT     = "MULE_ACCOUNT"      # Compte mule blanchiment — actuellement
                                            # détecté par heuristique brute dans
                                            # _detect_fraud_type(), PAS ENCORE relié
                                            # à BeneficiaryProfile.is_likely_mule()
                                            # (voir écarts documentés séparément)

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