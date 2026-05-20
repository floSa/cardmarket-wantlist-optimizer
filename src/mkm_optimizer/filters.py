"""
Filtres "durs" appliqués aux offres avant l'optimisation.

⚠️ Ce module ne fait PLUS de filtrage sur min_condition/languages/foil au
niveau global, parce que ça créait des FAUX NÉGATIFS : une carte avec
`min_condition: GD` côté want était bloquée par un `min_condition: EX`
global, alors qu'elle était parfaitement valide pour ce want précis.

Les contraintes par-want sont gérées plus finement par
`optimizer.compat.is_compatible` au moment de la construction du MIP.

Seuls les filtres TRULY globaux (insensibles au want) sont appliqués ici :
  - `excluded_sellers` : pseudos avec qui on refuse de traiter (litige passé)
  - éventuellement plus tard : seller_country/seller_type/min_reputation
    quand on récupérera ces métadonnées (TODO)
"""

from __future__ import annotations

from .models import Offer


def filter_offers(
    offers: list[Offer],
    excluded_sellers: list[str] | None = None,
    min_condition: str | None = None,    # ignoré, conservé pour compat de signature
    languages: list[str] | None = None,  # ignoré, idem
    foil: str | None = None,             # ignoré, idem
) -> list[Offer]:
    """
    Pré-filtre global. Aujourd'hui ne filtre que les `excluded_sellers`.
    Les autres params sont conservés dans la signature pour ne pas casser le
    CLI et `config.yaml` existants, mais ils sont volontairement ignorés (le
    matching fin est fait par compat.is_compatible).
    """
    excluded = {s.lower() for s in (excluded_sellers or [])}
    if not excluded:
        return list(offers)
    return [o for o in offers if o.seller.lower() not in excluded]
