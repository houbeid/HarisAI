"""
HarisAI — Port : IBeneficiaryStore
====================================
Interface abstraite pour le stockage des profils comportementaux des
BÉNÉFICIAIRES — symétrique à IProfileStore, mais côté destinataire.

Pourquoi un store séparé plutôt que d'étendre IProfileStore ?
    Un même TokenHash peut être à la fois client (expéditeur dans
    certaines transactions) ET bénéficiaire (destinataire dans d'autres).
    Les deux profils évoluent à des moments différents de la même
    transaction (le ClientProfile de l'expéditeur ET le
    BeneficiaryProfile du destinataire sont mis à jour ensemble),
    avec des clés Redis différentes pour éviter toute confusion entre
    "à qui j'envoie d'habitude" et "qui m'envoie d'habitude".

Implémentations :
    IBeneficiaryStore
    ├── RedisBeneficiaryStore    ← production (infrastructure/)
    └── InMemoryBeneficiaryStore ← tests unitaires
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from domain import Transaction, BeneficiaryProfile
from domain import TokenHash


class IBeneficiaryStore(ABC):
    """
    Contrat pour accéder et mettre à jour les profils comportementaux
    des bénéficiaires. Nécessaire pour détecter les comptes mules sans
    confondre avec un marchand légitime à fort volume de clients.
    """

    @abstractmethod
    async def get(
        self,
        beneficiary_token: TokenHash,
        operator: str
    ) -> Optional[BeneficiaryProfile]:
        """
        Récupère le profil comportemental d'un bénéficiaire.

        Args:
            beneficiary_token : hash anonyme du bénéficiaire
            operator           : ex: "BANKILY", "SEDAD", "MASRVI"

        Returns:
            BeneficiaryProfile si ce compte a déjà reçu des fonds
            None si c'est la première fois qu'il reçoit de l'argent
        """
        ...

    @abstractmethod
    async def update_inflow(
        self,
        profile: BeneficiaryProfile,
        transaction: Transaction
    ) -> None:
        """
        Met à jour le profil après une RÉCEPTION de fonds légitime confirmée.

        Ce que cette méthode met à jour :
        - known_sender_tokens (ajoute l'expéditeur si nouveau)
        - distinct_senders_30d (recalcule sur fenêtre glissante)
        - avg_amount_received_30d / total_received_30d
        - last_received_at (timestamp de cette réception)
        - total_transactions_received (incrémente de 1)

        Args:
            profile     : profil actuel du bénéficiaire
            transaction : transaction reçue à intégrer (où ce compte
                          est beneficiary_token)
        """
        ...

    @abstractmethod
    async def update_outflow(
        self,
        beneficiary_token: TokenHash,
        operator: str,
        outflow_at: datetime
    ) -> None:
        """
        Met à jour last_outflow_at quand ce compte envoie lui-même de
        l'argent (devient expéditeur dans une autre transaction).

        Appelé séparément de update_inflow car ce même compte agit
        alors comme client_token d'une AUTRE transaction — c'est le
        point d'observation clé pour mesurer la vélocité de sortie
        après réception, le signal central du pattern mule.

        Args:
            beneficiary_token : hash du compte qui envoie maintenant
            operator           : opérateur mobile money
            outflow_at          : timestamp de cette sortie de fonds
        """
        ...

    @abstractmethod
    async def create_default(
        self,
        beneficiary_token: TokenHash,
        operator: str
    ) -> BeneficiaryProfile:
        """
        Crée un profil bénéficiaire vide pour un compte qui reçoit
        de l'argent pour la première fois.

        Args:
            beneficiary_token : hash du nouveau bénéficiaire
            operator            : opérateur mobile money

        Returns:
            BeneficiaryProfile avec des valeurs par défaut
        """
        ...

    @abstractmethod
    async def delete(
        self,
        beneficiary_token: TokenHash,
        operator: str
    ) -> None:
        """
        Supprime le profil d'un bénéficiaire.
        Utilisé quand un compte ferme.

        Args:
            beneficiary_token : hash du bénéficiaire
            operator           : opérateur mobile money
        """
        ...