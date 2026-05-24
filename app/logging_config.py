"""
Налаштування логування для проєкту.
Файл експортує `logger`, який імпортується в `app.main`.
"""
import logging
import sys
from logging import Logger

from app.config import LOG_LEVEL


def _setup_logger(name: str = "ledolab") -> Logger:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not root_logger.handlers:
        root_handler = logging.StreamHandler(stream=sys.stdout)
        root_handler.setFormatter(fmt)
        root_logger.addHandler(root_handler)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = True
    return logger


logger = _setup_logger()

__all__ = ["logger"]
