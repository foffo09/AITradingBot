from __future__ import annotations

import logging
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(exist_ok=True)


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("aitradingbot")
    logger.setLevel(level.upper())
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(LOG_DIR / "aitradingbot.log", encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def safe_log_value(value: str | None) -> str:
    if not value:
        return "<missing>"
    return value[:4] + "***" if len(value) > 4 else "***"
