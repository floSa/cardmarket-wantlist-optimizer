"""
Chargement de la configuration (config.yaml + config.local.yaml).

Pas de magie : merge récursif simple, config.local écrase config.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier de config introuvable : {path}")
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # Surcharge optionnelle : config.local.yaml à côté
    local = path.parent / "config.local.yaml"
    if local.exists():
        with local.open("r", encoding="utf-8") as f:
            local_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, local_cfg)
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
