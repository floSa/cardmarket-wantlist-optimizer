"""
Parser de la page d'offres d'un vendeur, filtrée par wantlist.

URL type : https://www.cardmarket.com/fr/Magic/Users/<PSEUDO>/Offers/Singles
                                       ?sortBy=name_asc&idWantslist=<WANT_ID>

Une "article-row" = une offre. Sur une page filtrée par wantlist, on n'a que
les offres de ce vendeur qui correspondent à au moins une carte de la wantlist.

ATTENTION : le pseudo vendeur n'apparaît PAS dans chaque ligne — il est dans
l'URL et le titre de page. On le passe en paramètre (ou on le devine via
l'URL canonique présente dans <link rel="canonical">).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from selectolax.parser import HTMLParser, Node

from ..models import Condition, Foil, Offer
from ..selectors import (
    OFFER_ROW,
    OFFER_NAME_A,
    OFFER_NAME_FALLBACK_A,
    OFFER_SET_A,
    OFFER_CONDITION_A,
    OFFER_LANG_SPAN,
    OFFER_COMMENT,
    OFFER_PRICE,
    OFFER_AMOUNT,
    OFFER_ROW_ID_PREFIX,
    parse_condition,
    parse_language,
)


_RE_SELLER_FROM_URL = re.compile(r"/Users/([^/]+)/Offers/")
_RE_PRICE = re.compile(r"([\d.\s ]+),(\d{1,2})\s*€?")


def parse_seller_offers(
    html: str | Path,
    seller: str | None = None,
) -> tuple[str, list[Offer]]:
    """
    Parse les offres d'un vendeur. Retourne (pseudo, liste_d_offres).

    Si `seller` n'est pas fourni, le parser tente de le déduire du
    <link rel="canonical"> de la page (URL contient /Users/<pseudo>/).
    Lève ValueError si introuvable.
    """
    if isinstance(html, Path):
        html = html.read_text(encoding="utf-8")

    tree = HTMLParser(html)
    if seller is None:
        seller = _detect_seller(tree)
    if not seller:
        raise ValueError(
            "Impossible de déterminer le pseudo du vendeur. "
            "Passe-le en paramètre, ou vérifie que le HTML est une page "
            "/Users/<pseudo>/Offers/."
        )

    rows = tree.css(OFFER_ROW)
    offers: list[Offer] = []
    for row in rows:
        offer = _parse_row(row, seller)
        if offer is not None:
            offers.append(offer)
    return seller, offers


# ---- Détection vendeur depuis le HTML ---------------------------------------

def _detect_seller(tree: HTMLParser) -> str | None:
    # 1. <link rel="canonical" href="…/Users/<pseudo>/Offers/Singles">
    for sel in ("link[rel=canonical]", "meta[property='og:url']"):
        node = tree.css_first(sel)
        if node is None:
            continue
        href = node.attributes.get("href") or node.attributes.get("content") or ""
        m = _RE_SELLER_FROM_URL.search(href)
        if m:
            return m.group(1)
    # 2. Commentaire SingleFile en tête : "url: …/Users/<pseudo>/Offers/…"
    raw = tree.html or ""
    m = _RE_SELLER_FROM_URL.search(raw[:4000])
    if m:
        return m.group(1)
    return None


# ---- Parsing d'une ligne offre -----------------------------------------------

def _parse_row(row: Node, seller: str) -> Offer | None:
    # id="articleRow<id>"
    article_id: str | None = None
    raw_id = row.attributes.get("id", "")
    if raw_id and raw_id.startswith(OFFER_ROW_ID_PREFIX):
        article_id = raw_id[len(OFFER_ROW_ID_PREFIX):]

    # Nom + URL produit. NB : sur une page /Users/<v>/Offers, .col-seller
    # contient le nom de la CARTE (le vendeur est implicite).
    name_a = row.css_first(OFFER_NAME_A) or row.css_first(OFFER_NAME_FALLBACK_A)
    if name_a is None:
        return None
    card_name = (name_a.text(strip=True) or "").strip()
    product_url = (name_a.attributes.get("href") or "").strip()
    if not card_name or not product_url:
        return None

    # Set (édition concrète — pas de "Indifférent" possible ici, c'est une vraie offre)
    set_a = row.css_first(OFFER_SET_A)
    if set_a is None:
        return None
    set_label = (
        set_a.attributes.get("data-bs-original-title")
        or set_a.attributes.get("aria-label")
        or ""
    ).strip()

    # Condition
    cond_a = row.css_first(OFFER_CONDITION_A)
    cond_label = (
        cond_a.attributes.get("data-bs-original-title") if cond_a else None
    ) or (cond_a.css_first("span.badge").text(strip=True) if cond_a and cond_a.css_first("span.badge") else None)
    condition = parse_condition(cond_label)
    if condition is None and cond_a is not None:
        # Dernier recours : la classe condition-xx
        for cls in (cond_a.attributes.get("class") or "").split():
            if cls.startswith("condition-"):
                tag = cls.split("-", 1)[1].upper()
                try:
                    condition = Condition(tag)
                except ValueError:
                    pass
    if condition is None:
        return None

    # Langue (1 seule par offre, contrairement à la wantlist qui peut en lister plusieurs)
    lang_span = row.css_first(OFFER_LANG_SPAN)
    lang_label = (
        lang_span.attributes.get("data-bs-original-title") if lang_span else None
    )
    language = parse_language(lang_label) or "??"

    # Foil / Signed / Altered : icônes optionnelles dans .product-attributes
    # Présence d'une icône → True ; absence → False
    attrs_block = row.css_first(".product-attributes")
    foil_flag = _has_attribute_icon(attrs_block, {"Foil", "Reverse Holo", "Reverse Holographique"})
    signed_flag = _has_attribute_icon(attrs_block, {"Signed", "Signé"})
    altered_flag = _has_attribute_icon(attrs_block, {"Altered", "Altérée"})
    foil = Foil.YES if foil_flag else Foil.NO

    # Prix
    price_span = row.css_first(OFFER_PRICE)
    price_text = (price_span.text(strip=True) if price_span else "") or ""
    price = _parse_price(price_text)
    if price is None:
        return None

    # Quantité disponible
    amount_span = row.css_first(OFFER_AMOUNT)
    try:
        quantity = int((amount_span.text(strip=True) if amount_span else "1") or "1")
    except ValueError:
        quantity = 1

    # Commentaire vendeur (optionnel)
    comment_node = row.css_first(OFFER_COMMENT)
    comment = (
        (comment_node.attributes.get("data-bs-original-title") or comment_node.text(strip=True)).strip()
        if comment_node
        else None
    ) or None

    return Offer(
        seller=seller,
        card_name=card_name,
        product_url=product_url,
        set_label=set_label,
        condition=condition,
        language=language,
        foil=foil,
        is_signed=signed_flag,
        is_altered=altered_flag,
        price=price,
        quantity_available=quantity,
        article_id=article_id,
        comment=comment,
    )


def _has_attribute_icon(attrs_block: Node | None, labels: set[str]) -> bool:
    """
    Cherche une icône dont aria-label / data-bs-original-title matche un des
    labels donnés. Ces icônes ne sont présentes que si l'attribut s'applique.
    """
    if attrs_block is None:
        return False
    for el in attrs_block.css("[data-bs-original-title], [aria-label]"):
        title = (
            el.attributes.get("data-bs-original-title")
            or el.attributes.get("aria-label")
            or ""
        ).strip()
        if title in labels:
            return True
    return False


# ---- Prix au format français : "0,61 €" / "1.234,56 €" ----------------------

def _parse_price(text: str) -> Decimal | None:
    if not text:
        return None
    text = text.replace("\xa0", " ").replace("€", "").strip()
    if not text:
        return None
    # Format français : milliers en point (ou espace), décimales en virgule
    # On retire les séparateurs de milliers puis on remplace , par .
    cleaned = text.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
