"""
HarisAI — Dependencies FastAPI
================================
Injection de dépendances et configuration.

Settings : variables d'environnement chargées depuis .env
get_use_case() : fournit le use case configuré avec toutes ses dépendances
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Configuration du service ML.
    Chargée depuis les variables d'environnement ou le fichier .env
    """

    # API
    api_key:      str   = "harisai-secret-key-change-in-production"
    host:         str   = "0.0.0.0"
    port:         int   = 8001

    # Modèles ML
    model_path:            str = "models/xgboost_v1.0.0.pkl"
    isolation_forest_path: str = "models/isolation_forest_v1.0.0.pkl"
    tft_path:              str = "models/tft_v1.0.0.pkl"
    gnn_path:              str = "models/gnn_v1.0.0.pkl"
    model_version:         str = "1.0.0"

    # Redis
    redis_url:    str   = "redis://localhost:6379"

    # PostgreSQL
    database_url: str   = "postgresql+asyncpg://harisai:harisai@localhost/harisai"

    # MLflow
    mlflow_tracking_uri: str = "http://localhost:5000"

    # Opérateur (pour le Federated Learning futur)
    operator_name: str  = "BANKILY"

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    """
    Retourne la configuration — mise en cache après le premier appel.
    lru_cache garantit une seule instance partagée.
    """
    return Settings()