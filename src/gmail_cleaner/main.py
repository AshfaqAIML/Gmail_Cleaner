"""ASGI entry point: uvicorn gmail_cleaner.main:app --reload"""

from .api import app

__all__ = ["app"]
