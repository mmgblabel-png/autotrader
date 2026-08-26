"""WegMetDieKilos PayPro Campaign Automaton."""

from campaign_automaton.api import create_app
from campaign_automaton.runtime import build_runtime

__version__ = "1.0.0"
__all__ = ["build_runtime", "create_app"]
