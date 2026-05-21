"""
Handlers package initialization.
"""

from app.handlers.start import router as start_router
from app.handlers.quiz import router as quiz_router
from app.handlers.callbacks import router as callbacks_router

__all__ = [
    "start_router",
    "quiz_router",
    "callbacks_router",
]
