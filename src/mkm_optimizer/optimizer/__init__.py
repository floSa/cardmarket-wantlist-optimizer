"""Optimiseur d'achats (MIP exact via PuLP + CBC)."""
from .mip import solve
from .compat import is_compatible, normalize_name

__all__ = ["solve", "is_compatible", "normalize_name"]
