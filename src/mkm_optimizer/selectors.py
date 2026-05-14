"""
Centralisation des sélecteurs CSS et des tables de correspondance MKM.

Si le DOM de Cardmarket change, c'est le SEUL fichier à mettre à jour
(sauf cas vraiment exotique). Les parsers ne hardcodent jamais de sélecteur.
"""

from .models import Condition, Foil


# --- Wantlist (page /Wants/<id>) ---------------------------------------------

WANTLIST_TABLE_ID = "WantsListTable"

# Sélecteurs au sein d'un <tr role="row"> de la wantlist
WL_ROW = "tr[role=row]"
WL_AMOUNT_TD = "td.amount"           # `data-amount` attribut
WL_NAME_A = "td.name a"               # nom + URL produit
WL_EXPANSION_SPAN = "td.expansion span.visually-hidden"
WL_LANG_SPANS = "td.languages span.visually-hidden"
WL_CONDITION_SPAN = "td.condition span.visually-hidden"
WL_TERNARY_TDS = "td.ternary-header"  # ordre : foil, signed, altered
WL_TERNARY_ICON = "span[aria-label]"  # icône avec aria-label ∈ {Oui, Non, Indifférent}
WL_BUYPRICE_TD = "td.buyPrice"        # `data-text` attribut (0 si non renseigné)


# --- Offres vendeur (page /Users/<pseudo>/Offers/Singles) --------------------

OFFER_ROW = "div.article-row"                        # une offre = une article-row
OFFER_NAME_A = ".col-seller > a, .col-product .col-seller > a"  # selon profondeur
OFFER_NAME_FALLBACK_A = ".col-sellerProductInfo .col-seller a"
OFFER_SET_A = ".product-attributes a.expansion-symbol"
OFFER_CONDITION_A = ".product-attributes a.article-condition"
OFFER_LANG_SPAN = ".product-attributes span.icon[data-bs-original-title]"
OFFER_COMMENT = ".product-comments span[data-bs-original-title]"
OFFER_PRICE = ".price-container span.fw-bold"
OFFER_AMOUNT = ".amount-container span.item-count"
OFFER_ROW_ID_PREFIX = "articleRow"                   # id=articleRow<articleId>


# --- Tables de correspondance ------------------------------------------------

# Conditions : étiquettes MKM (FR + EN) → enum
CONDITION_FROM_LABEL: dict[str, Condition] = {
    # Anglais (utilisé par MKM dans data-bs-original-title)
    "Mint": Condition.MT,
    "Near Mint": Condition.NM,
    "Excellent": Condition.EX,
    "Good": Condition.GD,
    "Light Played": Condition.LP,
    "Played": Condition.PL,
    "Poor": Condition.PO,
    # Français (utilisé dans visually-hidden quand la page est en /fr/)
    "Bon": Condition.GD,
    "Joué légèrement": Condition.LP,
    "Joué": Condition.PL,
    "Mauvais": Condition.PO,
}

# Langues : étiquettes MKM (FR + EN) → code ISO court
LANG_FROM_LABEL: dict[str, str] = {
    "English": "en", "Anglais": "en",
    "French": "fr", "Français": "fr",
    "German": "de", "Allemand": "de",
    "Spanish": "es", "Espagnol": "es",
    "Italian": "it", "Italien": "it",
    "Japanese": "ja", "Japonais": "ja",
    "Portuguese": "pt", "Portugais": "pt",
    "Russian": "ru", "Russe": "ru",
    "Korean": "ko", "Coréen": "ko",
    "S-Chinese": "zh-Hans", "Chinois simplifié": "zh-Hans",
    "T-Chinese": "zh-Hant", "Chinois traditionnel": "zh-Hant",
    "Dutch": "nl", "Néerlandais": "nl",
    "Polish": "pl", "Polonais": "pl",
    "Czech": "cs", "Tchèque": "cs",
    "Hungarian": "hu", "Hongrois": "hu",
}

# Ternaires (foil/signed/altered) — étiquette aria-label → bool ou None
TERNARY_FROM_LABEL: dict[str, bool | None] = {
    "Oui": True,  "Yes": True,  "Y": True,
    "Non": False, "No": False,  "N": False,
    "Indifférent": None, "Any": None, "I": None,
}

# Foil dans une offre vendeur (l'icône foil n'est présente que si la carte est foil)
FOIL_FROM_TITLE: dict[str, Foil] = {
    "Foil": Foil.YES,
    "Reverse Holo": Foil.YES,
    "Reverse Holographique": Foil.YES,
}


def parse_condition(label: str | None) -> Condition | None:
    if not label:
        return None
    return CONDITION_FROM_LABEL.get(label.strip())


def parse_language(label: str | None) -> str | None:
    if not label:
        return None
    return LANG_FROM_LABEL.get(label.strip())


def parse_ternary(label: str | None) -> bool | None:
    if not label:
        return None
    return TERNARY_FROM_LABEL.get(label.strip())
