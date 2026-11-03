"""Strategie typowania. Rejestr: `REGISTRY` (nazwa -> klasa)."""
from lotto.strategies.base import REGISTRY, Strategy, get, register  # noqa: F401
from lotto.strategies import advanced, simple  # noqa: F401  (rejestruje strategie)
