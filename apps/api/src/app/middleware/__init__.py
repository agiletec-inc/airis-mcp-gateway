"""Middleware package"""

from .auth import optional_bearer_auth

__all__ = ["optional_bearer_auth"]
