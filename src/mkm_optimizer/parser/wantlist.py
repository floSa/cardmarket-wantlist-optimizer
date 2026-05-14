"""
Parser de la page wantlist Cardmarket (/fr/Magic/Wants/<id>).

Format DOM observé en mai 2026 sur une page sauvegardée avec SingleFile :
<table> dans #WantsListTable, chaque <tr role="row"> est une ligne.
Colonnes (par classe) : select, preview, amount, name, expansion, languages,
condition, 3× ternary-header (foil/signé/altéré), buyPrice, mailAlert, action.

Le parser ne fait AUCUN appel réseau — il prend du HTML brut et retourne
des dataclasses immutables.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from selectolax.parser import HTMLParser, Node

from ..models import Condition, Foil, WantEntry
from ..selectors import (
    WANTLIST_TABLE_ID,
    WL_ROW,
    WL_AMOUNT_TD,
    WL_NAME_A,
    WL_EXPANSION_SPAN,
    WL_LANG_SPANS,
    WL_CONDITION_SPAN,
    WL_TERNARY_TDS,
    WL_TERNARY_ICON,
    WL_BUYPRICE_TD,
    parse_condition,
    parse_language,
    parse_ternary,
)


# Regex pour extraire le set-code d'une URL produit Cardmarket.
# - Édition fixe : /fr/Magic/Products/Singles/<SET-SLUG>/<CARD-SLUG>?...
# - Metacard    : /fr/Magic/Cards/<CARD-SLUG>?...
_RE_SET_FROM_URL = re.compile(
    r"/[a-z]{2}/[^/]+/Products/Singles/(?P<set>[^/?]+)/[^/?]+"
)

_LOCALE_EXPANSION_INDIFFERENT = {"Indifférent", "Any", "Indifferent"}


def parse_wantlist(html: str | Path) -> list[WantEntry]:
    """
    Parse une wantlist Cardmarket et retourne la liste des wants.

    `html` peut être :
      - une str contenant le HTML brut
      - un Path vers un fichier HTML (auto-chargé)
    """
    if isinstance(html, Path):
        html = html.read_text(encoding="utf-8")

    tree = HTMLParser(html)
    table = tree.css_first(f"#{WANTLIST_TABLE_ID}")
    if table is None:
        raise ValueError(
            f"Section #{WANTLIST_TABLE_ID} introuvable. "
            "La page fournie n'est pas une page wantlist Cardmarket."
        )

    rows = table.css(f"tbody {WL_ROW}")
    entries: list[WantEntry] = []
    for row in rows:
        entry = _parse_row(row)
        if entry is not None:
            entries.append(entry)
    return entries


# ---- Parsing d'une ligne ----------------------------------------------------

def _parse_row(row: Node) -> WantEntry | None:
    # Quantité : <td data-amount="X" class="amount …">
    amount_td = row.css_first(WL_AMOUNT_TD)
    if amount_td is None:
        return None
    try:
        quantity = int(amount_td.attributes.get("data-amount", "0") or "0")
    except ValueError:
        return None
    if quantity <= 0:
        return None

    # Nom + URL produit
    name_a = row.css_first(WL_NAME_A)
    if name_a is None:
        return None
    card_name = (name_a.text(strip=True) or "").strip()
    # selectolax retourne href avec entités HTML décodées par défaut
    product_url = (name_a.attributes.get("href") or "").strip()
    if not card_name or not product_url:
        return None

    # Set : <td class="expansion …"><span class="visually-hidden">Indifférent|Magic 2013|...</span>
    set_label_node = row.css_first(WL_EXPANSION_SPAN)
    set_label_raw = (set_label_node.text(strip=True) if set_label_node else "") or ""
    set_label_raw = set_label_raw.strip()
    if set_label_raw in _LOCALE_EXPANSION_INDIFFERENT or not set_label_raw:
        set_label: str | None = None
        set_code: str | None = None
    else:
        set_label = set_label_raw
        # Si l'URL contient /Products/Singles/<SLUG>/, on a un code exact.
        m = _RE_SET_FROM_URL.search(product_url)
        set_code = m.group("set") if m else _slugify(set_label_raw)

    # Langues : on collecte tous les <span class="visually-hidden">Anglais|Français|...</span>
    lang_nodes = row.css(WL_LANG_SPANS)
    languages: list[str] = []
    for n in lang_nodes:
        code = parse_language(n.text(strip=True))
        if code and code not in languages:
            languages.append(code)

    # Condition minimum
    cond_node = row.css_first(WL_CONDITION_SPAN)
    min_cond = parse_condition(cond_node.text(strip=True) if cond_node else None) or Condition.EX

    # Foil / Signé / Altéré : 3 td.ternary-header dans l'ordre,
    # chaque td contient une icône avec aria-label ∈ {Oui, Non, Indifférent}.
    ternary_tds = row.css(WL_TERNARY_TDS)
    foil_bool, signed_bool, altered_bool = _parse_ternaries(ternary_tds)
    foil = (
        Foil.YES if foil_bool is True
        else Foil.NO if foil_bool is False
        else Foil.ANY
    )

    # Prix souhaité (max_price)
    max_price = _parse_max_price(row.css_first(WL_BUYPRICE_TD))

    return WantEntry(
        card_name=card_name,
        product_url=product_url,
        quantity=quantity,
        set_code=set_code,
        set_label=set_label,
        min_condition=min_cond,
        languages=languages,
        foil=foil,
        is_signed=signed_bool,
        is_altered=altered_bool,
        max_price=max_price,
    )


def _parse_ternaries(tds: Iterable[Node]) -> tuple[bool | None, bool | None, bool | None]:
    """
    Retourne (foil, signed, altered). None = indifférent.
    """
    out: list[bool | None] = [None, None, None]
    for i, td in enumerate(tds):
        if i >= 3:
            break
        icon = td.css_first(WL_TERNARY_ICON)
        label = icon.attributes.get("aria-label") if icon else None
        out[i] = parse_ternary(label)
    return out[0], out[1], out[2]


def _parse_max_price(td: Node | None) -> Decimal | None:
    """
    `<td data-text="0.71" class="buyPrice …"><span>0,71 €</span>`
    `<td data-text="0" class="buyPrice …">`         (pas de prix souhaité)
    """
    if td is None:
        return None
    raw = (td.attributes.get("data-text") or "").strip()
    if not raw or raw == "0":
        # Fallback : tenter le contenu du <span> avec virgule décimale
        span = td.css_first("span")
        if span is None:
            return None
        text = (span.text(strip=True) or "").replace("€", "").replace("\xa0", " ").strip()
        if not text:
            return None
        raw = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _slugify(s: str) -> str:
    """Slug minimal pour les set-codes quand l'URL n'en fournit pas."""
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


# ---- Métadonnées de la wantlist (titre, totaux affichés) --------------------

def parse_wantlist_meta(html: str | Path) -> dict[str, str | int | None]:
    """
    Lit le bloc <h2> "96 Wants - 233 Cartes" pour récupérer les compteurs
    annoncés par MKM (utile pour vérifier qu'on n'a rien raté au parsing).
    """
    if isinstance(html, Path):
        html = html.read_text(encoding="utf-8")
    tree = HTMLParser(html)
    title_node = tree.css_first("title")
    h2_node = tree.css_first(f"#{WANTLIST_TABLE_ID} h2")
    raw_h2 = h2_node.text(strip=True) if h2_node else ""
    m_wants = re.search(r"(\d+)\s+Wants?", raw_h2, re.IGNORECASE)
    m_cards = re.search(r"(\d+)\s+Cartes?", raw_h2, re.IGNORECASE) or re.search(
        r"(\d+)\s+Cards?", raw_h2, re.IGNORECASE
    )
    return {
        "title": title_node.text(strip=True).split("|")[0].strip() if title_node else None,
        "announced_wants": int(m_wants.group(1)) if m_wants else None,
        "announced_cards": int(m_cards.group(1)) if m_cards else None,
        "header_raw": raw_h2,
    }
