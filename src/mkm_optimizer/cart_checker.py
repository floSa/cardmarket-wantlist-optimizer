"""
Vérification panier vs recommandation du solveur.

Charge le CSV d'optimisation pour un scénario donné, compare avec le HTML
du panier, et génère un rapport Markdown listant divergences et confirmations.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .parser.cart import CartItem, CartSeller, parse_cart


# ---- Structures de résultat --------------------------------------------------

@dataclass
class LineIssue:
    card_name: str
    expansion: str
    kind: str        # "manquant" | "en_trop" | "qte" | "prix" | "set" | "condition"
    detail: str      # message lisible


@dataclass
class SellerResult:
    seller_name: str
    in_report: bool
    in_cart: bool
    issues: list[LineIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.in_report and self.in_cart and not self.issues


@dataclass
class CheckResult:
    scenario: str
    report_path: Path
    cart_path: Path
    seller_results: list[SellerResult]
    # cartes attendues dans le rapport
    report_total_qty: int
    report_total_price: Decimal
    report_total_shipping: Decimal
    # cartes dans le panier
    cart_total_qty: int
    cart_total_price: Decimal
    cart_total_shipping: Decimal

    @property
    def all_ok(self) -> bool:
        return all(s.ok for s in self.seller_results)

    @property
    def issue_count(self) -> int:
        return sum(len(s.issues) for s in self.seller_results) + sum(
            1 for s in self.seller_results if not s.in_cart or not s.in_report
        )


# ---- Chargement CSV ----------------------------------------------------------

def _parse_price(s: str) -> Decimal:
    """Convertit "1,50" ou "1.50" en Decimal."""
    return Decimal(s.replace(",", ".")) if s.strip() else Decimal("0")


@dataclass
class _ReportLine:
    seller: str
    card_name: str
    set_label: str
    condition: str
    language: str
    quantity: int
    unit_price: Decimal
    ship_cost: Decimal
    seller_total: Decimal


def load_scenario(csv_path: Path, scenario: str) -> list[_ReportLine]:
    """Charge toutes les lignes d'un scénario depuis le CSV d'optimisation."""
    lines: list[_ReportLine] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row.get("scenario") != scenario:
                continue
            lines.append(_ReportLine(
                seller=row["vendeur"],
                card_name=row["carte"],
                set_label=row["set"],
                condition=row["etat"],
                language=row["langue"],
                quantity=int(row["quantite"]),
                unit_price=_parse_price(row["prix_unitaire"]),
                ship_cost=_parse_price(row["fdp_vendeur"]),
                seller_total=_parse_price(row["total_vendeur"]),
            ))
    return lines


# ---- Comparaison -------------------------------------------------------------

def _normalize(s: str) -> str:
    return s.strip().lower()


def check_cart(
    cart_path: Path,
    csv_path: Path,
    scenario: str,
) -> CheckResult:
    report_lines = load_scenario(csv_path, scenario)
    if not report_lines:
        raise ValueError(f"Scénario '{scenario}' introuvable dans {csv_path}")

    cart_sellers = parse_cart(cart_path)

    # --- Index rapport : seller_norm → {card_norm → list[_ReportLine]}
    report_by_seller: dict[str, dict[str, list[_ReportLine]]] = {}
    for line in report_lines:
        s = _normalize(line.seller)
        c = _normalize(line.card_name)
        report_by_seller.setdefault(s, {}).setdefault(c, []).append(line)

    # --- Index panier : seller_norm → {card_norm → list[CartItem]}
    cart_by_seller: dict[str, dict[str, list[CartItem]]] = {}
    cart_seller_map: dict[str, CartSeller] = {}
    for cs in cart_sellers:
        s = _normalize(cs.seller_name)
        cart_seller_map[s] = cs
        for item in cs.items:
            c = _normalize(item.card_name)
            cart_by_seller.setdefault(s, {}).setdefault(c, []).append(item)

    all_sellers = set(report_by_seller) | set(cart_by_seller)
    seller_results: list[SellerResult] = []

    for s_norm in sorted(all_sellers):
        in_report = s_norm in report_by_seller
        in_cart = s_norm in cart_by_seller
        # Récupérer le nom d'affichage (avec casse d'origine)
        if in_report:
            display_name = report_by_seller[s_norm][next(iter(report_by_seller[s_norm]))][0].seller
        else:
            display_name = cart_seller_map[s_norm].seller_name

        issues: list[LineIssue] = []

        if not in_report:
            # Vendeur présent dans le panier mais absent du rapport
            issues.append(LineIssue("", "", "en_trop",
                f"Vendeur '{display_name}' absent du rapport — ajout non recommandé"))
        elif not in_cart:
            # Vendeur attendu mais absent du panier
            issues.append(LineIssue("", "", "manquant",
                f"Vendeur '{display_name}' absent du panier"))
        else:
            # Les deux présents : comparer carte par carte
            report_cards = report_by_seller[s_norm]
            cart_cards = cart_by_seller[s_norm]

            # Cartes attendues mais absentes du panier
            for c_norm, r_lines in report_cards.items():
                if c_norm not in cart_cards:
                    for rl in r_lines:
                        issues.append(LineIssue(
                            rl.card_name, rl.set_label, "manquant",
                            f"Attendu {rl.quantity}× à {rl.unit_price:.2f}€ ({rl.set_label}, {rl.condition}/{rl.language}) — absent du panier",
                        ))
                else:
                    # Carte présente : vérifier quantités et prix
                    cart_items = cart_cards[c_norm]
                    r_qty = sum(rl.quantity for rl in r_lines)
                    c_qty = sum(ci.quantity for ci in cart_items)
                    c_price = cart_items[0].unit_price  # 1er article (le plus probable)
                    r_price = r_lines[0].unit_price
                    card_name = r_lines[0].card_name
                    set_label = r_lines[0].set_label

                    if c_qty != r_qty:
                        issues.append(LineIssue(
                            card_name, set_label, "qte",
                            f"Quantité : rapport={r_qty} / panier={c_qty}",
                        ))
                    if c_price != r_price:
                        diff = c_price - r_price
                        sign = "+" if diff > 0 else ""
                        issues.append(LineIssue(
                            card_name, set_label, "prix",
                            f"Prix : rapport={r_price:.2f}€ / panier={c_price:.2f}€ ({sign}{diff:.2f}€)",
                        ))
                    # Vérifier le set si différent
                    cart_exp = cart_items[0].expansion
                    if _normalize(cart_exp) != _normalize(set_label):
                        issues.append(LineIssue(
                            card_name, set_label, "set",
                            f"Édition : rapport='{set_label}' / panier='{cart_exp}'",
                        ))

            # Cartes en trop dans le panier
            for c_norm, c_items in cart_cards.items():
                if c_norm not in report_cards:
                    for ci in c_items:
                        issues.append(LineIssue(
                            ci.card_name, ci.expansion, "en_trop",
                            f"{ci.quantity}× '{ci.card_name}' ({ci.expansion}) — absent du rapport",
                        ))

        seller_results.append(SellerResult(
            seller_name=display_name,
            in_report=in_report,
            in_cart=in_cart,
            issues=issues,
        ))

    # Totaux rapport
    r_qty = sum(l.quantity for l in report_lines)
    r_price = sum(l.unit_price * l.quantity for l in report_lines)
    seen_sellers: set[str] = set()
    r_shipping = Decimal("0")
    for l in report_lines:
        if l.seller not in seen_sellers:
            r_shipping += l.ship_cost
            seen_sellers.add(l.seller)

    # Totaux panier
    c_qty = sum(i.quantity for cs in cart_sellers for i in cs.items)
    c_price = sum(i.unit_price * i.quantity for cs in cart_sellers for i in cs.items)
    c_shipping = sum(cs.ship_cost for cs in cart_sellers)

    return CheckResult(
        scenario=scenario,
        report_path=csv_path,
        cart_path=cart_path,
        seller_results=seller_results,
        report_total_qty=r_qty,
        report_total_price=r_price,
        report_total_shipping=r_shipping,
        cart_total_qty=c_qty,
        cart_total_price=c_price,
        cart_total_shipping=c_shipping,
    )


# ---- Rendu Markdown ----------------------------------------------------------

def render_check_md(result: CheckResult) -> str:
    lines: list[str] = []
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    status_icon = "✅" if result.all_ok else "⚠️"
    lines.append(f"# {status_icon} Vérification panier — scénario `{result.scenario}`")
    lines.append(f"*Généré le {now}*")
    lines.append("")

    # --- Résumé global
    lines.append("## Résumé")
    if result.all_ok:
        lines.append("**✅ Panier conforme au rapport d'optimisation.**")
    else:
        lines.append(f"**⚠️ {result.issue_count} divergence(s) détectée(s).**")
    lines.append("")

    # Tableau totaux
    r_total = result.report_total_price + result.report_total_shipping
    c_total = result.cart_total_price + result.cart_total_shipping
    diff_qty = result.cart_total_qty - result.report_total_qty
    diff_price = c_total - r_total
    lines.append("| | Rapport | Panier | Écart |")
    lines.append("|---|---|---|---|")
    lines.append(f"| Cartes | {result.report_total_qty} | {result.cart_total_qty} | {diff_qty:+d} |")
    lines.append(f"| Cartes (€) | {result.report_total_price:.2f} € | {result.cart_total_price:.2f} € | {result.cart_total_price - result.report_total_price:+.2f} € |")
    lines.append(f"| FDP (€) | {result.report_total_shipping:.2f} € | {result.cart_total_shipping:.2f} € | {result.cart_total_shipping - result.report_total_shipping:+.2f} € |")
    lines.append(f"| **Total** | **{r_total:.2f} €** | **{c_total:.2f} €** | **{diff_price:+.2f} €** |")
    lines.append("")

    # --- Tableau vendeurs
    lines.append("## Vendeurs")
    lines.append("| Vendeur | Rapport | Panier | Statut |")
    lines.append("|---|---|---|---|")
    for sr in result.seller_results:
        r_icon = "✅" if sr.in_report else "➕"
        c_icon = "✅" if sr.in_cart else "❌"
        s_icon = "✅" if sr.ok else f"⚠️ {len(sr.issues)} problème(s)"
        lines.append(f"| {sr.seller_name} | {r_icon} | {c_icon} | {s_icon} |")
    lines.append("")

    # --- Détail par vendeur (seulement ceux avec problèmes)
    problem_sellers = [sr for sr in result.seller_results if not sr.ok]
    if problem_sellers:
        lines.append("## Détail des divergences")
        lines.append("")
        for sr in problem_sellers:
            lines.append(f"### ⚠️ {sr.seller_name}")
            lines.append("")
            # Grouper par type d'issue
            for kind_label, kind_key in [
                ("Cartes manquantes", "manquant"),
                ("Cartes en trop", "en_trop"),
                ("Quantités incorrectes", "qte"),
                ("Prix différents", "prix"),
                ("Éditions différentes", "set"),
                ("États différents", "condition"),
            ]:
                relevant = [i for i in sr.issues if i.kind == kind_key]
                if relevant:
                    lines.append(f"**{kind_label} :**")
                    lines.append("")
                    for issue in relevant:
                        if issue.card_name:
                            lines.append(f"- `{issue.card_name}` ({issue.expansion}) — {issue.detail}")
                        else:
                            lines.append(f"- {issue.detail}")
                    lines.append("")

    # --- Vendeurs OK
    ok_sellers = [sr for sr in result.seller_results if sr.ok]
    if ok_sellers:
        lines.append("## Vendeurs conformes")
        for sr in ok_sellers:
            lines.append(f"- ✅ **{sr.seller_name}**")
        lines.append("")

    return "\n".join(lines)


def write_check_report(result: CheckResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y_%m_%d_%H-%M")
    path = out_dir / f"{stamp}_CartCheck_{result.scenario}.md"
    path.write_text(render_check_md(result), encoding="utf-8")
    return path
