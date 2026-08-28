"""Compatibility export for the application composition root."""

# TODO: remove this module after callers import AppController from app.application_controller.
from .app.application_controller import AppController

__all__ = ["AppController"]
