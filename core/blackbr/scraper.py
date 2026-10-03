"""Sync (ELT) dos dados do painel Blackbr.

Kinds prefixados blackbr.* — não misturam com os outros painéis.
A base compartilhada é core/panel_scraper.py — correção vai no BASE, não
nas cópias (AGENTS.md G5). Este módulo é só config + wrappers; os testes
patcheiam save_entities/save_raw AQUI e a base resolve via cfg.module
(late binding) em tempo de chamada.
"""
import sys

from core import panel_scraper as _base
from core.database import count_entities, init_db, save_entities, save_raw  # re-export p/ testes
from core.blackbr.api import BLACKBR_API, BlackbrApiClient

_CFG = _base.ScraperConfig(name="blackbr", module=sys.modules[__name__], kinds_prefix="blackbr.")

CHARTS = _base.CHARTS


def sync_customers(client: BlackbrApiClient, pages: int = 1, per_page: int = 100) -> dict:
    return _base.sync_customers(_CFG, client, pages, per_page)


def sync_expiring(client: BlackbrApiClient) -> dict:
    return _base.sync_expiring(_CFG, client)


def sync_dashboard(client: BlackbrApiClient) -> dict:
    return _base.sync_dashboard(_CFG, client)


def sync_resellers(client: BlackbrApiClient) -> dict:
    return _base.sync_resellers(_CFG, client)


def sync_statistics(client: BlackbrApiClient) -> dict:
    return _base.sync_statistics(_CFG, client)


def sync_servers_packages(client: BlackbrApiClient) -> dict:
    return _base.sync_servers_packages(_CFG, client)


SYNCERS = {
    "customers": sync_customers,
    "expiring": sync_expiring,
    "dashboard": sync_dashboard,
    "resellers": sync_resellers,
    "statistics": sync_statistics,
    "servers_packages": sync_servers_packages,
}


def sync_all(client: BlackbrApiClient, pages: int = 5, per_page: int = 100) -> list[dict]:
    return _base.sync_all(_CFG, client, pages, per_page)


def entities_summary() -> dict:
    return _base.entities_summary(_CFG)
