"""Paper-only machine-learning utilities."""

from .shadow import OnlineLogistic, ShadowSignal, signal_from_recent, walk_forward

__all__ = ["OnlineLogistic", "ShadowSignal", "signal_from_recent", "walk_forward"]
