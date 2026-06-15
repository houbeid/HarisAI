"""
HarisAI — Data Loaders
========================
Registry de tous les loaders disponibles.

Ajouter un nouveau dataset :
    1. Crée mon_loader.py qui hérite de BaseLoader
    2. Ajoute-le dans REGISTRY ci-dessous
    3. C'est tout — train_xgboost.py ne change pas

Utilisation dans train_xgboost.py :
    from training.data_loaders import REGISTRY
    loader = REGISTRY["creditcard"]
    X, y = loader.load_and_validate("data/creditcard.csv")
"""

from .base_loader import BaseLoader
from .creditcard_loader import CreditcardLoader
from .pysim_loader import PysimLoader

# Registry — ajoute ici chaque nouveau loader
REGISTRY: dict[str, BaseLoader] = {
    "creditcard": CreditcardLoader(),
    "pysim":      PysimLoader(),
}

__all__ = [
    "BaseLoader",
    "CreditcardLoader",
    "PysimLoader",
    "BankilyLoader",
    "REGISTRY",
]