"""
CLI MKM Optimizer.

Commandes :
  optimize     run principal : wantlist + dossier HTMLs vendeurs → rapports MD/CSV
  parse        debug : affiche le contenu parsé d'une page MKM (wantlist OU vendeur)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .filters import filter_offers
from .models import Offer, Solution, WantEntry
from .optimizer.mip import brackets_from_config, solve
from .parser import parse_seller_offers, parse_wantlist
from .parser.wantlist import parse_wantlist_meta
from .reporter import write_reports


app = typer.Typer(
    name="mkm-optim",
    help="Optimiseur d'achats Cardmarket (MKM) — minimise coût total cartes + FDP.",
    add_completion=False,
)
console = Console()


# ---- Commande : optimize ----------------------------------------------------

@app.command()
def optimize(
    wantlist: Path = typer.Option(
        ..., "--wantlist", "-w", exists=True, dir_okay=False, file_okay=True, readable=True,
        help="HTML de la page wantlist Cardmarket (/fr/Magic/Wants/<id>).",
    ),
    sellers_dir: Path = typer.Option(
        ..., "--sellers-dir", "-s", exists=True, file_okay=False, dir_okay=True, readable=True,
        help="Dossier contenant les HTMLs de vendeurs (un fichier par vendeur).",
    ),
    config: Path = typer.Option(
        Path("config.yaml"), "--config", "-c", exists=True, readable=True,
        help="Fichier de configuration YAML.",
    ),
    output_dir: Path = typer.Option(
        Path("reports"), "--output-dir", "-o",
        help="Dossier de sortie pour les rapports MD/CSV.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Lance l'optimisation et écrit les rapports."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s :: %(message)s",
    )

    cfg = load_config(config)
    brackets = brackets_from_config(cfg["shipping"]["brackets"])
    filt = cfg.get("filters", {})

    # --- Wantlist
    console.print(f"[bold]→ Wantlist[/bold] : {wantlist}")
    wants = parse_wantlist(wantlist)
    meta = parse_wantlist_meta(wantlist)
    title = meta.get("title")
    console.print(
        f"  {len(wants)} wants / {sum(w.quantity for w in wants)} cartes"
        f" — titre : {title!r}"
    )

    # --- Offres : tous les HTMLs du dossier
    console.print(f"[bold]→ Vendeurs[/bold] : {sellers_dir}")
    raw_offers: list[Offer] = []
    sellers_seen: list[str] = []
    for html_path in sorted(sellers_dir.glob("*.html")):
        try:
            seller, offers = parse_seller_offers(html_path)
        except Exception as e:
            console.print(f"  [yellow]⚠[/yellow] {html_path.name} : ignoré ({e})")
            continue
        sellers_seen.append(seller)
        raw_offers.extend(offers)
        console.print(f"  · {seller:<20s}  {len(offers):>4d} offres")
    console.print(
        f"  TOTAL : {len(sellers_seen)} vendeur(s), {len(raw_offers)} offres brutes"
    )
    if not raw_offers:
        console.print("[red]Aucune offre à optimiser — abandon.[/red]")
        raise typer.Exit(code=2)

    # --- Filtrage global
    offers = filter_offers(
        raw_offers,
        excluded_sellers=filt.get("excluded_sellers", []),
        min_condition=filt.get("min_condition"),
        languages=filt.get("languages"),
        foil=filt.get("foil"),
    )
    console.print(
        f"  Après filtres globaux : {len(offers)} offres "
        f"({len(raw_offers) - len(offers)} écartées)"
    )

    # --- Optimisation par scénario
    solutions: list[Solution] = []
    for sc in cfg["optimization"]["scenarios"]:
        sol = solve(
            wants=wants,
            offers=offers,
            brackets=brackets,
            max_vendors=sc.get("max_vendors"),
            scenario_name=sc["name"],
        )
        solutions.append(sol)
        _print_scenario_summary(sol)

    # --- Écriture rapports
    md_path, csv_path = write_reports(solutions, wants, out_dir=output_dir, title=title)
    console.print(f"\n[bold green]✓ Rapport MD[/bold green]  : {md_path}")
    console.print(f"[bold green]✓ Rapport CSV[/bold green] : {csv_path}")


def _print_scenario_summary(sol: Solution) -> None:
    t = Table(title=f"Scénario : {sol.scenario_name}", show_lines=False, expand=False)
    t.add_column("Vendeur", style="cyan", no_wrap=True)
    t.add_column("Cartes", justify="right")
    t.add_column("Sous-total", justify="right")
    t.add_column("FDP", justify="right")
    t.add_column("Total", justify="right", style="bold")
    for b in sol.baskets:
        t.add_row(
            b.seller,
            str(b.total_units),
            f"{b.cards_subtotal:.2f} €",
            f"{b.shipping_cost:.2f} €",
            f"{b.grand_total:.2f} €",
        )
    t.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{sum(b.total_units for b in sol.baskets)}[/bold]",
        f"[bold]{sol.cards_total:.2f} €[/bold]",
        f"[bold]{sol.shipping_total:.2f} €[/bold]",
        f"[bold]{sol.grand_total:.2f} €[/bold]",
    )
    console.print(t)
    if sol.unmet_wants:
        miss = sum(w.quantity for w in sol.unmet_wants)
        console.print(
            f"[yellow]⚠ {len(sol.unmet_wants)} wants non couverts ({miss} cartes)[/yellow]"
        )


# ---- Commande : parse (debug) -----------------------------------------------

@app.command()
def parse(
    html: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    kind: str = typer.Option(
        "auto", "--kind", "-k",
        help="auto | wantlist | seller",
    ),
) -> None:
    """Parse un HTML et affiche le contenu (debug)."""
    if kind == "auto":
        # Heuristique : la wantlist contient "WantsListTable", les offres contiennent "article-row".
        text = html.read_text(encoding="utf-8", errors="ignore")
        kind = "wantlist" if "WantsListTable" in text else "seller"

    if kind == "wantlist":
        wants = parse_wantlist(html)
        meta = parse_wantlist_meta(html)
        console.print(f"[bold]Wantlist[/bold] {meta.get('title')!r} — {meta.get('header_raw')}")
        console.print(f"Parsés : {len(wants)} wants / {sum(w.quantity for w in wants)} cartes")
        for w in wants[:30]:
            console.print(
                f"  qty={w.quantity:>2d}  {w.card_name!r:<55s}  "
                f"set={(w.set_label or 'ANY'):<25s}  ≥{w.min_condition.value}  langs={w.languages}"
            )
    elif kind == "seller":
        seller, offers = parse_seller_offers(html)
        console.print(f"[bold]Vendeur[/bold] : {seller!r} — {len(offers)} offres")
        for o in offers[:30]:
            console.print(
                f"  {o.card_name!r:<55s}  set={o.set_label:<25s}  "
                f"{o.condition.value} {o.language}  {o.price} € x{o.quantity_available}"
            )
    else:
        raise typer.BadParameter(f"kind inconnu : {kind!r}")


if __name__ == "__main__":
    app()
