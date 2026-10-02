"""Centralised logging for AutoTrader."""

import logging
import os
from logging.handlers import RotatingFileHandler


def get_logger(name: str, log_file: str = "autotrader.log", level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger that writes to both console and a rotating file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler (5 MB × 3 backups). Runtime logs belong outside the
    # installed Python package so the process can run as an unprivileged user.
    log_dir = os.path.abspath(
        os.getenv("AUTOTRADER_LOG_DIR") or os.path.join(os.getcwd(), "logs")
    )
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(log_dir, log_file),
            maxBytes=5_000_000,
            backupCount=3,
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError as exc:
        # Console logging remains available; inability to write a local log
        # file must not crash a container before health checks can run.
        logger.warning("File logging disabled for %s: %s", log_dir, type(exc).__name__)

    return logger
