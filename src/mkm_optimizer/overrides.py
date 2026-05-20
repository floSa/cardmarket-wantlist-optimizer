"""
Surcharges locales pour la wantlist parsée.

Le fichier `wantlist_overrides.yaml` à la racine du projet permet de modifier
les attributs d'un want SANS toucher à la wantlist MKM ni re-télécharger l'HTML.
Très pratique pour ajuster un prix souhaité, augmenter/baisser une quantité,
relâcher une contrainte d'état (NM → EX), etc.

Format :
    overrides:
      - card: "Éthérien doué"
        max_price: 0.75
      - card: "Anneau solaire"
        max_price: 1.50
        min_condition: NM
        languages: [fr]

Le matching se fait par nom de carte normalisé (sans accents/case/V.N).
Si la carte n'existe pas dans la wantlist, on logge un warning mais on
continue (peut-être que tu as retiré la carte depuis).
"""

from __future__ import annotations

import dataclasses
import logging
from decimal import Decimal
from pathlib import Path

import yaml

from .models import Condition, Foil, WantEntry
from .optimizer.compat import normalize_name


log = logging.getLogger(__name__)


OVERRIDABLE_FIELDS = {
    "max_price",
    "quantity",
    "min_condition",
    "languages",
    "foil",
    "is_signed",
    "is_altered",
}


def apply_wantlist_overrides(
    wants: list[WantEntry],
    overrides_path: str | Path,
) -> list[WantEntry]:
    """
    Applique le fichier d'overrides à la liste de wants parsée.

    Si le fichier n'existe pas → retourne la liste inchangée (silencieux).
    Si une carte de l'override n'est pas trouvée → warning, on saute.
    """
    p = Path(overrides_path)
    if not p.exists():
        return wants

    try:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        log.error("Fichier d'override invalide (%s) : %s", p, e)
        return wants

    overrides = cfg.get("overrides") or []
    if not overrides:
        return wants

    # Index par clé normalisée pour matching tolérant aux accents / V.N / casse
    by_key: dict[str, WantEntry] = {normalize_name(w.card_name): w for w in wants}

    matched = 0
    unmatched: list[str] = []
    bad_fields: list[str] = []

    for entry in overrides:
        card_name = entry.get("card") or entry.get("card_name")
        if not card_name:
            continue
        key = normalize_name(card_name)
        if key not in by_key:
            unmatched.append(card_name)
            continue

        new_kwargs: dict = {}
        for field, value in entry.items():
            if field in ("card", "card_name"):
                continue
            if field not in OVERRIDABLE_FIELDS:
                bad_fields.append(f"{card_name}.{field}")
                continue
            new_kwargs[field] = _coerce(field, value)

        if new_kwargs:
            by_key[key] = dataclasses.replace(by_key[key], **new_kwargs)
            matched += 1
            log.info("Override appliqué à %r : %s", card_name, new_kwargs)

    if unmatched:
        log.warning(
            "%d cartes d'override introuvables dans la wantlist (skip) : %s",
            len(unmatched),
            ", ".join(unmatched),
        )
    if bad_fields:
        log.warning(
            "Champs inconnus dans les overrides (ignorés) : %s",
            ", ".join(bad_fields),
        )
    log.info("Overrides : %d carte(s) modifiée(s)", matched)

    return list(by_key.values())


def _coerce(field: str, value):
    """Convertit la valeur YAML brute vers le type attendu par WantEntry."""
    if value is None:
        return None
    if field == "max_price":
        return Decimal(str(value))
    if field == "quantity":
        return int(value)
    if field == "min_condition":
        return Condition(str(value).upper())
    if field == "languages":
        return list(value) if isinstance(value, list) else [str(value)]
    if field == "foil":
        return Foil(str(value).lower())
    if field in ("is_signed", "is_altered"):
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("any", "indifferent", "indifférent"):
                return None
            return v in ("true", "yes", "oui", "1")
        return bool(value)
    return value
