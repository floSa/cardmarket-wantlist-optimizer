"""
Authentification Cardmarket via Playwright.

Flux :
  1. Première fois → `mkm-optim login` ouvre Chromium en headed.
     Tu te logues manuellement (identifiant + mot de passe + éventuel 2FA).
     Une fois sur ton tableau de bord, on sauvegarde l'état du navigateur
     (cookies + localStorage) dans `.auth/storage_state.json`.
  2. Runs suivants → on relit ce fichier, Chromium démarre déjà connecté.
     Aucun mot de passe ne transite par notre code.

Pas de credentials en clair, jamais. C'est toi qui les tapes dans le navigateur.
"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import (
    BrowserContext,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)


STORAGE_STATE_PATH = Path(".auth/storage_state.json")
MKM_BASE = "https://www.cardmarket.com"
LOGIN_URL = f"{MKM_BASE}/fr/Magic/Login"

# Page d'accueil utilisateur connecté : présence d'un lien /Account ou /Wants
LOGGED_IN_PROBE = f"{MKM_BASE}/fr/Magic"
LOGGED_IN_SELECTOR = "a[href*='/Account'], a[href*='/Wants/']"

# User-Agent honnête (pas de spoof "real human"). On garde l'UA Playwright
# par défaut sauf si l'on souhaite forcer un Firefox stable. Cloudflare
# fingerprint surtout TLS + WebGL, pas l'UA pur.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

log = logging.getLogger(__name__)


# ---- Première connexion (interactive, headed) -------------------------------

def interactive_login(storage_path: Path = STORAGE_STATE_PATH) -> None:
    """
    Ouvre Chromium headed sur la page de login MKM. L'utilisateur se logue
    manuellement, puis on sauvegarde l'état du browser.

    On considère le login "réussi" quand le bouton "Mon compte" / un lien
    /Account devient présent dans la page. On laisse 5 minutes max.
    """
    storage_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(user_agent=USER_AGENT, locale="fr-FR")
        page = ctx.new_page()

        log.info("Ouverture de %s — connecte-toi dans la fenêtre.", LOGIN_URL)
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print()
        print("=" * 70)
        print("  CONNEXION CARDMARKET")
        print("=" * 70)
        print(f"  1. Tape ton identifiant + mot de passe dans la fenêtre Chromium")
        print(f"  2. Si MKM te demande un CAPTCHA / 2FA, fais-le manuellement")
        print(f"  3. Une fois sur ton tableau de bord, REVIENS ICI et appuie ENTRÉE")
        print("=" * 70)
        try:
            input("  > Appuie sur ENTRÉE quand tu es connecté(e)... ")
        except (EOFError, KeyboardInterrupt):
            print("Connexion annulée.")
            browser.close()
            return

        # Sanity check : on attend rapidement la présence d'un marqueur "logged-in"
        try:
            page.wait_for_selector(LOGGED_IN_SELECTOR, timeout=5_000)
            log.info("Marqueur de session détecté.")
        except PWTimeoutError:
            log.warning(
                "Aucun marqueur de connexion détecté. "
                "On sauvegarde quand même la session — vérifie qu'elle marche "
                "avec `mkm-optim fetch` sur 1 vendeur."
            )

        ctx.storage_state(path=str(storage_path))
        browser.close()
        print(f"\n✓ Session sauvegardée dans {storage_path}")
        print("  Tu n'auras plus besoin de te reconnecter tant que MKM la conserve")
        print("  (typiquement 30 jours). Sinon relance `mkm-optim login`.\n")


# ---- Réutilisation de la session pour les runs suivants ---------------------

def get_authenticated_context(
    playwright: Playwright,
    headless: bool = True,
    storage_path: Path = STORAGE_STATE_PATH,
) -> tuple[object, BrowserContext]:
    """
    Lance un navigateur Chromium en réutilisant le storage_state existant.
    Retourne (browser, context). À l'appelant de les fermer.

    Lève RuntimeError si pas de session enregistrée.
    """
    if not storage_path.exists():
        raise RuntimeError(
            f"Pas de session enregistrée ({storage_path}). "
            "Lance d'abord : mkm-optim login"
        )
    browser = playwright.chromium.launch(headless=headless)
    ctx = browser.new_context(
        storage_state=str(storage_path),
        user_agent=USER_AGENT,
        locale="fr-FR",
        viewport={"width": 1366, "height": 900},
    )
    return browser, ctx


def is_session_valid(ctx: BrowserContext, timeout_ms: int = 15_000) -> bool:
    """
    Vérifie rapidement que la session stockée fonctionne encore : si on charge
    une page utilisateur, on doit voir le bouton "Mon compte".
    """
    page = ctx.new_page()
    try:
        page.goto(LOGGED_IN_PROBE, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_selector(LOGGED_IN_SELECTOR, timeout=5_000)
            return True
        except PWTimeoutError:
            return False
    except PWTimeoutError:
        return False
    finally:
        page.close()
