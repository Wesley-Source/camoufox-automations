"""
Sync (ELT) dos dados do painel Sigma.

Cada sync_* recebe um SigmaApiClient já aberto (CLI/MCP abrem com
open_client() — um boot de browser por comando) e grava:
- bruto em raw_snapshots (save_raw)
- cópia limpa em panel_entities com UPSERT (save_entity)

Todas as chamadas são GET — read-only por construção.
"""
from core.database import count_entities, init_db, save_entity, save_raw
from core.sigma.api import SIGMA_API, SigmaApiClient

CHARTS = ("new-customers", "customer-retention", "revenue-forecast", "lost-revenue")


def sync_customers(client: SigmaApiClient, pages: int = 1, per_page: int = 100) -> dict:
    init_db()
    synced, page = 0, 1
    for page in range(1, pages + 1):
        data = client.customers(page, per_page)
        save_raw(f"{SIGMA_API}/customers?page={page}", data)
        for row in data["data"]:
            save_entity("customer", row["id"], row)
            synced += 1
        if page >= data.get("meta", {}).get("last_page", page):
            break
    return {"what": "customers", "synced": synced, "pages": page, "status": "synced"}


def sync_expiring(client: SigmaApiClient) -> dict:
    init_db()
    data = client.customers_expiring()
    save_raw(f"{SIGMA_API}/customers/expiring", data)
    rows = data.get("data", data if isinstance(data, list) else [])
    for i, row in enumerate(rows):
        save_entity("expiring", row.get("id", i), row)
    return {"what": "expiring", "synced": len(rows), "status": "synced"}


def sync_dashboard(client: SigmaApiClient) -> dict:
    init_db()
    synced = 0
    for name in CHARTS:
        payload = client.dashboard_chart(name)
        save_raw(f"{SIGMA_API}/dashboard/charts/{name}", payload)
        save_entity("dashboard_chart", name, payload)
        synced += 1
    payload = client.dashboard_recovery()
    save_raw(f"{SIGMA_API}/dashboard/metrics/recovery", payload)
    save_entity("dashboard_metric", "recovery", payload)
    synced += 1
    return {"what": "dashboard", "synced": synced, "status": "synced"}


def sync_resellers(client: SigmaApiClient) -> dict:
    init_db()
    rows = client.resellers()
    save_raw(f"{SIGMA_API}/resellers/list", rows)
    for row in rows:
        save_entity("reseller", row["id"], row)
    return {"what": "resellers", "synced": len(rows), "status": "synced"}


def sync_statistics(client: SigmaApiClient) -> dict:
    init_db()
    data = client.customers_statistics()
    save_raw(f"{SIGMA_API}/customers/statistics", data)
    inner = data.get("data", data)
    for key, value in inner.items():
        save_entity("customer_stats", key, value)
    return {"what": "statistics", "synced": len(inner), "status": "synced"}


SYNCERS = {
    "customers": sync_customers,
    "expiring": sync_expiring,
    "dashboard": sync_dashboard,
    "resellers": sync_resellers,
    "statistics": sync_statistics,
}


def sync_all(client: SigmaApiClient, pages: int = 5, per_page: int = 100) -> list[dict]:
    return [sync_customers(client, pages, per_page)] + [
        SYNCERS[name](client) for name in ("expiring", "dashboard", "resellers", "statistics")
    ]


def entities_summary() -> dict:
    """Contagem por kind — para status/monitoramento."""
    init_db()
    kinds = ("customer", "expiring", "dashboard_chart", "dashboard_metric",
             "reseller", "customer_stats")
    return {k: count_entities(k) for k in kinds}
