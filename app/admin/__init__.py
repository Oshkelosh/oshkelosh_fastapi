"""
Oshkelosh admin panel – Jinja2 server-rendered admin interface.

Exports the FastAPI router mounted at ``/admin`` in main.py.
"""

from app.admin.routes import router

__all__ = ["router"]
