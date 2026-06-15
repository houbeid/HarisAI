"""
HarisAI — Port : IProfileStore
================================
Interface abstraite pour le stockage des profils comportementaux clients.

Le use case ne sait pas si les profils sont dans Redis, PostgreSQL,
ou en mémoire (pour les tests). Il appelle juste get() et update().

Implémentations :
    IProfileStore
    ├── RedisProfileStore    ← production (infrastructure/)
    └── InMemoryProfileStore ← tests unitaires
"""

from abc import ABC, abstractmethod
from typing import Optional

from domain import Transaction, ClientProfile
from domain import TokenHash


class IProfileStore(ABC):
    """
    Contrat pour accéder et mettre à jour les profils comportementaux.
    Les profils sont la mémoire du système — ils permettent de détecter
    les déviations par rapport au comportement normal d'un client.
    """

    @abstractmethod
    async def get(
        self,
        client_token: TokenHash,
        operator: str
    ) -> Optional[ClientProfile]:
        """
        Récupère le profil comportemental d'un client.

        Args:
            client_token : hash anonyme du client
            operator     : ex: "BANKILY", "SEDAD", "MASRVI"

        Returns:
            ClientProfile si le client est connu
            None si c'est un nouveau client (première transaction)
        """
        ...

    @abstractmethod
    async def update(
        self,
        profile: ClientProfile,
        transaction: Transaction
    ) -> None:
        """
        Met à jour le profil après une transaction légitime confirmée.
        Appelé seulement pour les transactions APPROVE ou les faux positifs.

        Ce que cette méthode met à jour :
        - avg_amount_7d / avg_amount_30d (moyenne glissante)
        - std_amount_7d (écart-type glissant)
        - usual_zones (ajoute la zone si pas déjà présente)
        - known_device_ids (ajoute le device si nouveau)
        - usual_hours (ajoute l'heure si pas déjà présente)
        - last_transaction_at (timestamp de la dernière tx)
        - total_transactions (incrémente de 1)

        Args:
            profile     : profil actuel du client
            transaction : transaction légitime à intégrer
        """
        ...

    @abstractmethod
    async def create_default(
        self,
        client_token: TokenHash,
        operator: str
    ) -> ClientProfile:
        """
        Crée un profil vide pour un nouveau client.
        Utilisé quand get() retourne None (première transaction).

        Le profil vide signifie :
        - Aucun historique → moins de contexte pour XGBoost
        - Tout sera "nouveau" → scores légèrement plus élevés
        - S'enrichit progressivement après chaque transaction légitime

        Args:
            client_token : hash du nouveau client
            operator     : opérateur mobile money

        Returns:
            ClientProfile avec des valeurs par défaut
        """
        ...

    @abstractmethod
    async def delete(
        self,
        client_token: TokenHash,
        operator: str
    ) -> None:
        """
        Supprime le profil d'un client.
        Utilisé quand un client ferme son compte.

        Args:
            client_token : hash du client
            operator     : opérateur mobile money
        """
        ...