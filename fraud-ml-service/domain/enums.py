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
    """
    # Fraudes mobile money spécifiques Mauritanie
    SIM_SWAPPING     = "SIM_SWAPPING"      # Clonage SIM
    OTP_THEFT        = "OTP_THEFT"         # Vol code OTP
    USSD_SCAM        = "USSD_SCAM"         # Arnaque *888#
    FAKE_MERCHANT    = "FAKE_MERCHANT"     # Faux compte marchand
    FRAUDULENT_AGENT = "FRAUDULENT_AGENT"  # Agent Bankily frauduleux

    # Fraudes AML
    STRUCTURING      = "STRUCTURING"       # Smurfing sous seuil BCM
    LAYERING         = "LAYERING"          # Circulation entre comptes
    MULE_ACCOUNT     = "MULE_ACCOUNT"      # Compte mule blanchiment

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