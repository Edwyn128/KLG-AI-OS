"""
limiter.py — Shared slowapi rate limiter instance.

Extracted from main.py to avoid circular imports: main.py registers the limiter
on app.state, and route files import it from here (not from main.py).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
