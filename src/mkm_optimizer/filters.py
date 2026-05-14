"""
Filtres "durs" appliqués aux offres avant l'optimisation.

On retire ici les offres qui ne peuvent JAMAIS satisfaire la wantlist quels
que soient les autres choix : mauvaise langue universelle, foil non voulu,
vendeur exclu, etc. Le matching offre↔want fin est ensuite fait par
optimizer.compat.is_compatible.
"""

from __future__ import annotations

from .models import Foil, Offer


def filter_offers(
    offers: list[Offer],
    excluded_sellers: list[str] | None = None,
    min_condition: str | None = None,
    languages: list[str] | None = None,
    foil: str | None = None,
) -> list[Offer]:
    """
    Pré-filtre global qui s'applique avant le MIP.

    Note : les contraintes par-want (min_condition spécifique, langue précise…)
    sont appliquées plus finement dans compat.is_compatible. Ici on filtre
    seulement les offres qui sont incompatibles avec TOUS les wants à coup sûr.
    """
    from .models import Condition

    excluded = {s.lower() for s in (excluded_sellers or [])}
    min_cond_enum = Condition(min_condition) if min_condition else None
    foil_filter = Foil(foil) if foil and foil != "any" else None
    accepted_langs = set(languages) if languages else None

    out: list[Offer] = []
    for o in offers:
        if o.seller.lower() in excluded:
            continue
        if min_cond_enum and not o.condition.at_least(min_cond_enum):
            continue
        if accepted_langs and o.language not in accepted_langs:
            continue
        if foil_filter and o.foil != foil_filter:
            continue
        out.append(o)
    return out
