"""
Export d'une wantlist parsée vers un CSV lisible.

Le CSV est généré à chaque run `optimize` à côté du rapport (et également
disponible via la commande `mkm-optim wantlist-csv` pour usage standalone).

Séparateur `;` (compat tableurs FR), encodage UTF-8 avec BOM pour qu'Excel
détecte bien les accents.

Format des colonnes :
  qty               quantité demandée
  card_name         nom de la carte (tel qu'affiché sur MKM)
  set_code          slug EN du set ("Seventh-Edition") OU vide si metacard
  set_label         libellé localisé ("Septième Edition") OU "toutes éditions"
  is_metacard       true/false
  min_condition     MT / NM / EX / GD / LP / PL / PO
  languages         codes ISO séparés par "|" (ex : fr|en)
  foil              yes / no / any
  is_signed         true/false/any
  is_altered        true/false/any
  max_price_eur     prix max souhaité (vide si non renseigné)
  product_url       URL MKM (utile pour vérifier ce que MKM voit)
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .models import WantEntry


WANTLIST_CSV_COLUMNS = [
    "qty",
    "card_name",
    "set_code",
    "set_label",
    "is_metacard",
    "min_condition",
    "languages",
    "foil",
    "is_signed",
    "is_altered",
    "max_price_eur",
    "product_url",
]


def render_wantlist_csv(wants: Sequence[WantEntry]) -> str:
    """Rend la wantlist sous forme CSV (séparateur `;`). Tri alpha par nom."""
    rows = [";".join(WANTLIST_CSV_COLUMNS)]
    for w in sorted(wants, key=lambda x: x.card_name.lower()):
        rows.append(";".join([
            str(w.quantity),
            _safe(w.card_name),
            _safe(w.set_code or ""),
            _safe(w.set_label or ("toutes éditions" if w.is_metacard else "")),
            "true" if w.is_metacard else "false",
            w.min_condition.value,
            "|".join(w.languages),
            w.foil.value,
            _tri(w.is_signed),
            _tri(w.is_altered),
            _fmt_price(w.max_price),
            _safe(w.product_url),
        ]))
    return "\n".join(rows) + "\n"


def write_wantlist_csv(wants: Sequence[WantEntry], path: Path) -> Path:
    """Écrit le CSV à `path`. Crée les dossiers parents si nécessaires."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # BOM UTF-8 pour Excel — sinon les accents s'affichent en mojibake
    content = "﻿" + render_wantlist_csv(wants)
    path.write_text(content, encoding="utf-8")
    return path


# ---- Helpers ----------------------------------------------------------------

def _safe(s: str) -> str:
    """Échappe les caractères qui casseraient un CSV à séparateur `;`."""
    if any(c in s for c in (";", '"', "\n", "\r")):
        return '"' + s.replace('"', '""') + '"'
    return s


def _tri(v: bool | None) -> str:
    if v is None:
        return "any"
    return "true" if v else "false"


def _fmt_price(v) -> str:
    if v is None:
        return ""
    s = f"{v:.2f}".replace(".", ",")
    return s
