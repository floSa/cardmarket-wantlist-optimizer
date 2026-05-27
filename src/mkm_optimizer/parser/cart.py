"""
Parser du panier Cardmarket (page /fr/Magic/ShoppingCart sauvegardée avec SingleFile).

Structure HTML cible :
  section.shipment-block[data-item-value, data-ship-cost]
    .seller-name          → pseudo du vendeur
    tr[data-article-id]   → une ligne article
      data-name           → nom de la carte
      data-expansion-name → nom du set
      data-amount         → quantité
      data-price          → prix unitaire (float string)
      data-condition      → code état MKM (1=MT 2=NM 3=EX 4=GD 5=LP 6=PL 7=PO)
      data-language       → code langue MKM (1=en 2=fr 3=de 4=es 5=it 7=ja …)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from selectolax.parser import HTMLParser

# Codes MKM → valeurs lisibles
_CONDITION: dict[int, str] = {
    1: "MT", 2: "NM", 3: "EX", 4: "GD", 5: "LP", 6: "PL", 7: "PO",
}
_LANGUAGE: dict[int, str] = {
    1: "en", 2: "fr", 3: "de", 4: "es", 5: "it",
    6: "zh-hans", 7: "ja", 8: "pt", 9: "ru", 10: "ko", 11: "zh-hant",
}


@dataclass
class CartItem:
    article_id: str
    card_name: str
    expansion: str
    condition: str   # "NM", "EX", …
    language: str    # "fr", "en", …
    quantity: int
    unit_price: Decimal


@dataclass
class CartSeller:
    seller_name: str
    items: list[CartItem]
    items_total: Decimal   # valeur cartes (data-item-value)
    ship_cost: Decimal     # FDP (data-ship-cost)

    @property
    def total_quantity(self) -> int:
        return sum(i.quantity for i in self.items)

    @property
    def grand_total(self) -> Decimal:
        return self.items_total + self.ship_cost


def parse_cart(html_path: Path) -> list[CartSeller]:
    """Parse un HTML SingleFile du panier Cardmarket. Retourne la liste des vendeurs."""
    html = html_path.read_text(encoding="utf-8")
    tree = HTMLParser(html)

    sellers: list[CartSeller] = []
    for section in tree.css("section.shipment-block"):
        name_node = section.css_first(".seller-name")
        if not name_node:
            continue
        seller_name = name_node.text(strip=True)

        try:
            items_total = Decimal(section.attributes.get("data-item-value", "0"))
            ship_cost = Decimal(section.attributes.get("data-ship-cost", "0"))
        except Exception:
            items_total = Decimal("0")
            ship_cost = Decimal("0")

        items: list[CartItem] = []
        for row in section.css("tr[data-article-id]"):
            a = row.attributes
            try:
                cond = _CONDITION.get(int(a.get("data-condition", 0)), "?")
                lang = _LANGUAGE.get(int(a.get("data-language", 0)), "?")
                items.append(CartItem(
                    article_id=a.get("data-article-id", ""),
                    card_name=a.get("data-name", ""),
                    expansion=a.get("data-expansion-name", ""),
                    condition=cond,
                    language=lang,
                    quantity=int(a.get("data-amount", 1)),
                    unit_price=Decimal(a.get("data-price", "0")),
                ))
            except Exception:
                continue

        sellers.append(CartSeller(
            seller_name=seller_name,
            items=items,
            items_total=items_total,
            ship_cost=ship_cost,
        ))

    return sellers
