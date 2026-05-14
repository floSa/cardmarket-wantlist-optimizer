"""
Génération des rapports d'achat (Markdown + CSV).

Le rapport Markdown est lisible en l'état, et la section
"Récapitulatif par carte" rend visibles les splits de quantité.
Le CSV est destiné à un import tableur pour suivi/budget.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .models import Solution, WantEntry


# ---- Markdown ---------------------------------------------------------------

def render_markdown(
    solutions: list[Solution],
    wants: list[WantEntry],
    title: str | None = None,
) -> str:
    """
    Génère un rapport Markdown complet listant tous les scénarios.
    """
    lines: list[str] = []
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"# Rapport d'achat MKM — {stamp}")
    if title:
        lines.append(f"_Wantlist : **{title}** — {len(wants)} wants / {sum(w.quantity for w in wants)} cartes_")
    lines.append("")

    for sol in solutions:
        lines.extend(_render_scenario_md(sol, wants))
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _render_scenario_md(sol: Solution, all_wants: list[WantEntry]) -> list[str]:
    out: list[str] = []
    vendor_count = sol.vendor_count
    out.append(f"## Scénario : `{sol.scenario_name}` ({vendor_count} vendeur{'s' if vendor_count > 1 else ''})")
    out.append(
        f"**Total : {_fmt_eur(sol.grand_total)}** "
        f"(cartes : {_fmt_eur(sol.cards_total)} + FDP : {_fmt_eur(sol.shipping_total)})"
    )
    if sol.unmet_wants:
        missing_units = sum(w.quantity for w in sol.unmet_wants)
        out.append(
            f"⚠️ **{len(sol.unmet_wants)} wants non couverts ({missing_units} cartes manquantes)** "
            "— voir section dédiée en fin de scénario."
        )
    out.append("")

    # Détail par vendeur
    for i, basket in enumerate(sol.baskets, start=1):
        out.append(f"### Vendeur {i} : `{basket.seller}`")
        out.append("")
        out.append("| Carte | Set | État | Langue | Foil | Qté | PU | Total |")
        out.append("|---|---|---|---|---|---:|---:|---:|")
        # On regroupe par (carte, set, état, langue, foil, prix) pour aérer
        for a in sorted(
            basket.assignments,
            key=lambda x: (x.offer.card_name.lower(), x.offer.set_label, x.offer.price),
        ):
            o = a.offer
            foil_lbl = "Foil" if o.foil.value == "yes" else "-"
            out.append(
                f"| {o.card_name} | {o.set_label} | {o.condition.value} | {o.language} | {foil_lbl} "
                f"| {a.quantity} | {_fmt_eur(o.price)} | {_fmt_eur(a.line_total)} |"
            )
        out.append(f"| **Sous-total cartes** | | | | | **{basket.total_units}** | | **{_fmt_eur(basket.cards_subtotal)}** |")
        out.append(f"| **FDP** | | | | | | | **{_fmt_eur(basket.shipping_cost)}** |")
        out.append(f"| **TOTAL** | | | | | | | **{_fmt_eur(basket.grand_total)}** |")
        out.append("")

    # Récap par carte (clé pour valider les splits)
    out.append("### Récapitulatif par carte")
    coverage = _coverage_by_card(sol, all_wants)
    for want_key, info in coverage.items():
        w = info["want"]
        parts = info["parts"]
        covered = sum(p["qty"] for p in parts)
        missing = w.quantity - covered
        bullet = f"- **{w.card_name}** (qté demandée : {w.quantity})"
        if not parts:
            out.append(f"{bullet} → ❌ aucune offre compatible")
            continue
        chunks = []
        running_total = Decimal("0")
        for p in parts:
            chunks.append(
                f"{p['qty']}× chez `{p['seller']}` ({p['set']}, {p['cond']}, {p['lang']}, {_fmt_eur(p['unit'])})"
            )
            running_total += Decimal(p["qty"]) * p["unit"]
        suffix = f" = {_fmt_eur(running_total)}"
        if missing > 0:
            suffix += f" — ⚠️ il manque encore {missing}"
        out.append(f"{bullet} → " + " + ".join(chunks) + suffix)
    if sol.unmet_wants:
        out.append("")
        out.append("#### Wants entièrement non couverts")
        for w in sol.unmet_wants:
            out.append(f"- {w.quantity}× **{w.card_name}** ({w.set_label or 'toutes éditions'})")

    return out


def _coverage_by_card(sol: Solution, all_wants: list[WantEntry]) -> dict[str, dict]:
    """
    Construit, pour chaque want, la liste des morceaux d'achat qui le couvrent.
    Pour l'instant on matche par nom de carte normalisé — cohérent avec compat.py.
    """
    from .optimizer.compat import normalize_name

    by_key: dict[str, dict] = {}
    for w in all_wants:
        by_key[normalize_name(w.card_name)] = {"want": w, "parts": []}
    for basket in sol.baskets:
        for a in basket.assignments:
            k = normalize_name(a.offer.card_name)
            if k not in by_key:
                # Ne devrait pas arriver, mais on évite le KeyError
                continue
            by_key[k]["parts"].append(
                {
                    "seller": basket.seller,
                    "set": a.offer.set_label,
                    "cond": a.offer.condition.value,
                    "lang": a.offer.language,
                    "qty": a.quantity,
                    "unit": a.offer.price,
                }
            )
    return by_key


# ---- CSV --------------------------------------------------------------------

CSV_COLUMNS = [
    "scenario", "vendeur", "carte", "set", "etat", "langue", "foil",
    "quantite", "prix_unitaire", "ligne_total", "fdp_vendeur", "total_vendeur"
]


def render_csv(solutions: list[Solution]) -> str:
    """CSV plat — une ligne par achat élémentaire."""
    out = []
    out.append(";".join(CSV_COLUMNS))
    for sol in solutions:
        for basket in sol.baskets:
            for a in basket.assignments:
                o = a.offer
                row = [
                    sol.scenario_name,
                    basket.seller,
                    _csv_safe(o.card_name),
                    _csv_safe(o.set_label),
                    o.condition.value,
                    o.language,
                    o.foil.value,
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
    Écrit le rapport MD et le CSV dans `out_dir`, retourne les 2 chemins.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"rapport_{stamp}.md"
    csv_path = out_dir / f"rapport_{stamp}.csv"
    md_path.write_text(render_markdown(solutions, wants, title=title), encoding="utf-8")
    csv_path.write_text(render_csv(solutions), encoding="utf-8")
    return md_path, csv_path
