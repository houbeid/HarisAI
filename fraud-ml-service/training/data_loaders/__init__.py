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
from .aryan_loader import AryanLoader
from .ibm_aml_loader import IBMAMLLoader

# Registry — ajoute ici chaque nouveau loader
REGISTRY: dict[str, BaseLoader] = {
    "creditcard": CreditcardLoader(),
    "pysim":      PysimLoader(),
    "aryan":      AryanLoader(low_memory=True),   # local machine
    "aryan_full": AryanLoader(low_memory=False),  # Kaggle 30GB RAM
    "ibm_aml":      IBMAMLLoader(low_memory=True),   # local machine
    "ibm_aml_full": IBMAMLLoader(low_memory=False),  # Kaggle 30GB RAM
}

__all__ = [
    "BaseLoader",
    "CreditcardLoader",
    "PysimLoader",
    "BankilyLoader",
    "REGISTRY",
]