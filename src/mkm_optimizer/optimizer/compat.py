"""
Test de compatibilité offre ↔ ligne de wantlist.

Une offre est "compatible" avec un want si elle satisfait toutes les
contraintes dures (édition, condition, langue, foil, etc.). C'est ce qui
détermine quelles offres entrent dans le MIP pour chaque want.

Pas de notion de prix ici — le prix est géré uniquement par l'objectif du MIP.
"""

from __future__ import annotations

import re
import unicodedata

from ..models import Foil, Offer, WantEntry


# ---- Normalisation de noms / slugs ------------------------------------------

def normalize_name(s: str) -> str:
    """
    Normalise un nom de carte pour matching : sans accents, lower, espaces
    et ponctuation collapsés en un seul espace.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


def normalize_set(s: str | None) -> str | None:
    """
    Slug minimal d'un nom de set, pour matcher w.set_code (slug URL) avec
    offer.set_label (libellé affiché traduit).

    Ce n'est pas parfait : "Lorwyn éclipsé" et "Lorwyn-Eclipsed" ne donneront
    pas le même slug. Si tu rencontres ce souci, ajoute des alias dans
    `SET_ALIASES`.
    """
    if s is None:
        return None
    base = normalize_name(s).replace(" ", "-")
    return SET_ALIASES.get(base, base)


# Aliases pour réconcilier slug-EN (URL produit) ↔ libellé-FR (page offre)
# À enrichir au fil des cas observés.
SET_ALIASES: dict[str, str] = {
    "lorwyn-eclipse": "lorwyn-eclipsed",
    "edition-de-base-2020": "core-set-2020",
    "magic-2013": "magic-2013",
    "fondations": "foundations",
}


# ---- Test de compatibilité ---------------------------------------------------

def is_compatible(offer: Offer, want: WantEntry) -> bool:
    """
    Renvoie True si l'offre peut couvrir tout ou partie du want.

    Règles :
    - Nom de la carte : identique (normalisé).
    - Set : si want spécifique → slugs normalisés égaux. Metacard → libre.
    - Condition : offer.condition ≥ want.min_condition (rang ≤).
    - Langue : si want.languages non vide, offer.language doit y figurer.
    - Foil : NO/YES doivent matcher ; ANY accepte tout.
    - Signed / Altered : si renseigné dans le want (True/False), doit matcher.
    """
    # Nom
    if normalize_name(offer.card_name) != normalize_name(want.card_name):
        return False

    # Set (seulement si want non-metacard)
    if not want.is_metacard:
        if normalize_set(offer.set_label) != normalize_set(want.set_code):
            return False

    # Condition (rank: MT=0 < NM < EX < … < PO=6)
    if not offer.condition.at_least(want.min_condition):
        return False

    # Langue
    if want.languages and offer.language not in want.languages:
        return False

    # Foil
    if want.foil != Foil.ANY:
        if want.foil != offer.foil:
            return False

    # Signed (None côté want = indifférent)
    if want.is_signed is True and not offer.is_signed:
        return False
    if want.is_signed is False and offer.is_signed:
        return False

    # Altered (None côté want = indifférent)
    if want.is_altered is True and not offer.is_altered:
        return False
    if want.is_altered is False and offer.is_altered:
        return False

    return True
