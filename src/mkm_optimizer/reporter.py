"""
Génération des rapports d'achat (Markdown + CSV).

Format du rapport :
  1. En-tête : titre + métadonnées wantlist
  2. Tableau comparatif des scénarios (vendeurs, cartes, FDP, total, manquants…)
  3. Pour chaque scénario :
       a. Détail par vendeur (tableau avec colonne PxD = Prix max désiré)
       b. Section "Wants entièrement non couverts" (si applicable)

Fichiers en sortie : `YYYY_MM_DD_HH-MM_WantListOptimized.{md,csv}`
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .models import Solution, WantEntry
from .optimizer.compat import normalize_name


# ---- Helpers : mapping wantlist → infos par carte ---------------------------

def _wants_index(wants: list[WantEntry]) -> dict[str, WantEntry]:
    """
    Index nom-normalisé → WantEntry. Si une carte apparaît plusieurs fois
    dans la wantlist (rare), on garde la 1re entrée pour les infos d'affichage
    (max_price, set_label).
    """
    idx: dict[str, WantEntry] = {}
    for w in wants:
        k = normalize_name(w.card_name)
        idx.setdefault(k, w)
    return idx


def _max_price_for_offer(card_name: str, wants_idx: dict[str, WantEntry]) -> Decimal | None:
    w = wants_idx.get(normalize_name(card_name))
    return w.max_price if w else None


# ---- Markdown ---------------------------------------------------------------

def render_markdown(
    solutions: list[Solution],
    wants: list[WantEntry],
    title: str | None = None,
) -> str:
    """Rapport Markdown complet : en-tête + comparatif + détail par scénario."""
    lines: list[str] = []
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"# Rapport d'achat MKM — {stamp}")
    if title:
        n_wants = len(wants)
        n_cards = sum(w.quantity for w in wants)
        lines.append(f"_Wantlist : **{title}** — {n_wants} wants / {n_cards} cartes_")
    lines.append("")

    # Tableau comparatif des scénarios
    lines.extend(_render_scenarios_comparison(solutions, wants))
    lines.append("")

    wants_idx = _wants_index(wants)

    for sol in solutions:
        lines.append("---")
        lines.append("")
        lines.extend(_render_scenario_md(sol, wants, wants_idx))
        lines.append("")

    return "\n".join(lines)


# ---- Tableau comparatif (intro du rapport) ----------------------------------

def _render_scenarios_comparison(
    solutions: list[Solution],
    wants: list[WantEntry],
) -> list[str]:
    out: list[str] = []
    out.append("## Comparatif des scénarios")
    out.append("")
    out.append(
        "| Scénario | Vendeurs | Cartes achetées | Cartes manquantes | "
        "Wants non couverts | Coût cartes | FDP | **TOTAL** |"
    )
    out.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|"
    )
    total_wants = len(wants)
    total_cards_requested = sum(w.quantity for w in wants)
    for sol in solutions:
        cards_bought = sum(b.total_units for b in sol.baskets)
        cards_missing = total_cards_requested - cards_bought
        out.append(
            f"| `{sol.scenario_name}` "
            f"| {sol.vendor_count} "
            f"| {cards_bought} / {total_cards_requested} "
            f"| {cards_missing} "
            f"| {len(sol.unmet_wants)} / {total_wants} "
            f"| {_fmt_eur(sol.cards_total)} "
            f"| {_fmt_eur(sol.shipping_total)} "
            f"| **{_fmt_eur(sol.grand_total)}** |"
        )
    return out


# ---- Détail d'un scénario ---------------------------------------------------

def _render_scenario_md(
    sol: Solution,
    all_wants: list[WantEntry],
    wants_idx: dict[str, WantEntry],
) -> list[str]:
    """
    Bloc scénario en mode compact. Format :

      ## Scénario : `<name>` (N vendeurs)

      Total : X € (cartes : Y € + FDP : Z €) ⚠️ N wants non couverts (M cartes)

      **Cartes manquantes** (totales ou partielles)

      * X/Y NomCarte (édition) ❌|⚠️
      * ...

      **Vendeurs :**
      Nom1 (X cartes, Y €), Nom2 (X cartes, Y €), ...
    """
    out: list[str] = []
    vendor_count = sol.vendor_count
    out.append(
        f"## Scénario : `{sol.scenario_name}` "
        f"({vendor_count} vendeur{'s' if vendor_count > 1 else ''})"
    )
    out.append("")

    # Ligne de total : pas de gras sur "Total", warning unmet inline
    line = (
        f"Total : {_fmt_eur(sol.grand_total)} "
        f"(cartes : {_fmt_eur(sol.cards_total)} + FDP : {_fmt_eur(sol.shipping_total)})"
    )
    if sol.unmet_wants:
        missing_units = sum(w.quantity for w in sol.unmet_wants)
        line += f" ⚠️ {len(sol.unmet_wants)} wants non couverts ({missing_units} cartes manquantes)"
    out.append(line)
    out.append("")

    # Cartes manquantes (totales ou partielles) — section en premier
    uncovered = _uncovered_wants(sol, all_wants)
    if uncovered:
        out.append("**Cartes manquantes** (totales ou partielles)")
        out.append("")
        for w, missing in uncovered:
            edition_label = w.set_label if (w.set_code and w.set_label) else "toutes éditions"
            marker = ""
            if missing == w.quantity:
                marker = " ❌"
            elif missing > 0:
                marker = " ⚠️"
            out.append(f"* {missing}/{w.quantity} {w.card_name} ({edition_label}){marker}")
        out.append("")

    # Liste compacte des vendeurs : 1 ligne, séparés par virgules
    # Tri par grand_total décroissant (le plus important d'abord)
    if sol.baskets:
        baskets_sorted = sorted(sol.baskets, key=lambda b: b.grand_total, reverse=True)
        parts = [
            f"{b.seller} ({b.total_units} cartes, {_fmt_eur(b.grand_total)})"
            for b in baskets_sorted
        ]
        out.append("**Vendeurs :**")
        out.append(", ".join(parts))
        out.append("")

        # Détail par vendeur (tableaux pour passer la commande)
        for i, basket in enumerate(baskets_sorted, start=1):
            out.append(f"### Vendeur {i} : `{basket.seller}`")
            out.append("")
            out.append("| Carte | Set | État | Langue | Foil | PxD | Qté | PU | Total |")
            out.append("|---|---|---|---|---|---:|---:|---:|---:|")
            for a in sorted(
                basket.assignments,
                key=lambda x: (x.offer.card_name.lower(), x.offer.set_label, x.offer.price),
            ):
                o = a.offer
                foil_lbl = "Foil" if o.foil.value == "yes" else "-"
                pxd = _max_price_for_offer(o.card_name, wants_idx)
                pxd_str = _fmt_eur(pxd) if pxd else "-"
                out.append(
                    f"| {o.card_name} | {o.set_label} | {o.condition.value} | {o.language} | {foil_lbl} "
                    f"| {pxd_str} | {a.quantity} | {_fmt_eur(o.price)} | {_fmt_eur(a.line_total)} |"
                )
            out.append(
                f"| **Sous-total cartes** | | | | | | **{basket.total_units}** | | "
                f"**{_fmt_eur(basket.cards_subtotal)}** |"
            )
            out.append(f"| **FDP** | | | | | | | | **{_fmt_eur(basket.shipping_cost)}** |")
            out.append(f"| **TOTAL** | | | | | | | | **{_fmt_eur(basket.grand_total)}** |")
            out.append("")

    return out


def _uncovered_wants(sol: Solution, all_wants: list[WantEntry]) -> list[tuple[WantEntry, int]]:
    """
    Retourne la liste (want_original, nb_manquants) pour tous les wants qui
    ont au moins un exemplaire non couvert dans cette solution — qu'ils
    soient totalement non couverts (4/4) ou partiellement (1/3).

    `sol.unmet_wants` contient une copie du want avec `quantity` = slack.
    On le remappe sur le want d'origine pour avoir la quantité demandée
    totale et le set_label correct.
    """
    full_index: dict[str, WantEntry] = {
        normalize_name(w.card_name): w for w in all_wants
    }
    out: list[tuple[WantEntry, int]] = []
    for u in sol.unmet_wants:
        k = normalize_name(u.card_name)
        if k in full_index:
            out.append((full_index[k], u.quantity))
    out.sort(key=lambda x: x[0].card_name.lower())
    return out


# ---- CSV --------------------------------------------------------------------

CSV_COLUMNS = [
    "scenario", "vendeur", "carte", "set", "etat", "langue", "foil",
    "pxd", "quantite", "prix_unitaire", "ligne_total",
    "fdp_vendeur", "total_vendeur",
]


def render_csv(solutions: list[Solution], wants: list[WantEntry]) -> str:
    """CSV plat — une ligne par achat élémentaire (séparateur `;`)."""
    wants_idx = _wants_index(wants)
    out = [";".join(CSV_COLUMNS)]
    for sol in solutions:
        for basket in sol.baskets:
            for a in basket.assignments:
                o = a.offer
                pxd = _max_price_for_offer(o.card_name, wants_idx)
                row = [
                    sol.scenario_name,
                    basket.seller,
                    _csv_safe(o.card_name),
                    _csv_safe(o.set_label),
                    o.condition.value,
                    o.language,
                    o.foil.value,
                    _fmt_dec(pxd) if pxd else "",
                    str(a.quantity),
                    _fmt_dec(o.price),
                    _fmt_dec(a.line_total),
                    _fmt_dec(basket.shipping_cost),
                    _fmt_dec(basket.grand_total),
                ]
                out.append(";".join(row))
    return "\n".join(out) + "\n"


# ---- Helpers ----------------------------------------------------------------

def _fmt_eur(v: Decimal) -> str:
    """Format euro : '12,34 €' (FR)."""
    s = f"{v:.2f}".replace(".", ",")
    return f"{s} €"


def _fmt_dec(v: Decimal) -> str:
    """Format Decimal sans symbole, virgule décimale."""
    return f"{v:.2f}".replace(".", ",")


def _csv_safe(s: str) -> str:
    """Échappe les ; et " pour CSV (séparateur ;)."""
    if ";" in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


# ---- Écriture sur disque ----------------------------------------------------

def write_reports(
    solutions: list[Solution],
    wants: list[WantEntry],
    out_dir: Path,
    title: str | None = None,
    timestamp: str | None = None,
) -> tuple[Path, Path]:
    """
    Écrit le rapport MD + CSV dans `out_dir`, retourne (md_path, csv_path).
    Convention de nom : `YYYY_MM_DD_HH-MM_WantListOptimized.{md,csv}`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y_%m_%d_%H-%M")
    base = f"{stamp}_WantListOptimized"
    md_path = out_dir / f"{base}.md"
    csv_path = out_dir / f"{base}.csv"
    md_path.write_text(render_markdown(solutions, wants, title=title), encoding="utf-8")
    csv_path.write_text(render_csv(solutions, wants), encoding="utf-8")
    return md_path, csv_path
