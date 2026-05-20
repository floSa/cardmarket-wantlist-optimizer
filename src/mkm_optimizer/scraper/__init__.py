"""Scraping Cardmarket via Playwright (option B du brief).

Modules :
  - auth   : login interactif + storage_state persisté
  - fetch  : récupération paginatée des offres vendeur
"""
from .auth import login, interactive_login, get_authenticated_context, STORAGE_STATE_PATH
from .fetch import fetch_seller, fetch_all_sellers, FetchStats

__all__ = [
    "login",
    "interactive_login",
    "get_authenticated_context",
    "STORAGE_STATE_PATH",
    "fetch_seller",
    "fetch_all_sellers",
    "FetchStats",
]
