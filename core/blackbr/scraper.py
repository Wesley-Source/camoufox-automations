"""
Sync (ELT) dos dados do painel Sigma.

Cada sync_* recebe um BlackbrApiClient já aberto (CLI/MCP abrem com
open_client() — um boot de browser por comando) e grava:
- bruto em raw_snapshots (save_raw)
- cópia limpa em panel_entities com UPSERT (save_entities)

Todas as chamadas são GET — read-only por construção.
"""
from core.database import count_entities, init_db, save_entities, save_raw
from core.blackbr.api import BLACKBR_API, BlackbrApiClient

CHARTS = ("new-customers", "customer-retention", "revenue-forecast", "lost-revenue")


def sync_customers(client: BlackbrApiClient, pages: int = 1, per_page: int = 100) -> dict:
    init_db()
    synced, page = 0, 1
    pages = max(1, pages)  # pages=0 silenciosamente não sincronizava nada
    for page in range(1, pages + 1):
        data = client.customers(page, per_page)
        save_raw(f"{BLACKBR_API}/customers?page={page}", data)
        rows = data["data"]
        # M-baixa: lote único (1 conexão/commit) em vez de 1 por linha.
        synced += save_entities("blackbr.customer", [(r["id"], r) for r in rows])
        # CR-23: sem meta.last_page (shape inesperado), só paramos com a
        # página vazia — nunca presumimos que a p1 é a última.
        last_page = data.get("meta", {}).get("last_page")
        if not rows or (last_page is not None and page >= last_page):
            break
    return {"what": "customers", "synced": synced, "pages": page, "status": "synced"}


def sync_expiring(client: BlackbrApiClient) -> dict:
    init_db()
    data = client.customers_expiring()
    save_raw(f"{BLACKBR_API}/customers/expiring", data)
    rows = data.get("data", data if isinstance(data, list) else [])
    saved = 0
    pairs = []
    for row in rows:
        # M4: sem id, o upsert usaria o índice como external_id e misturaria
        # clientes diferentes entre runs — pula.
        if not row.get("id"):
            continue
        pairs.append((row["id"], row))
        saved += 1
    save_entities("blackbr.expiring", pairs)
    return {"what": "expiring", "synced": saved, "status": "synced"}


def sync_dashboard(client: BlackbrApiClient) -> dict:
    init_db()
    synced = 0
    for name in CHARTS:
        payload = client.dashboard_chart(name)
        save_raw(f"{BLACKBR_API}/dashboard/charts/{name}", payload)
        save_entities("blackbr.dashboard_chart", [(name, payload)])
        synced += 1
    payload = client.dashboard_recovery()
    save_raw(f"{BLACKBR_API}/dashboard/metrics/recovery", payload)
    save_entities("blackbr.dashboard_metric", [("recovery", payload)])
    synced += 1
    return {"what": "dashboard", "synced": synced, "status": "synced"}


def sync_resellers(client: BlackbrApiClient) -> dict:
    init_db()
    rows = client.resellers()
    save_raw(f"{BLACKBR_API}/resellers/list", rows)
    save_entities("blackbr.reseller", [(r["id"], r) for r in rows])
    return {"what": "resellers", "synced": len(rows), "status": "synced"}


def sync_statistics(client: BlackbrApiClient) -> dict:
    init_db()
    data = client.customers_statistics()
    save_raw(f"{BLACKBR_API}/customers/statistics", data)
    inner = data.get("data", data)
    save_entities("blackbr.customer_stats", list(inner.items()))
    return {"what": "statistics", "synced": len(inner), "status": "synced"}


def sync_servers_packages(client: BlackbrApiClient) -> dict:
    """Catálogo de servers + packages — valida o par package↔server antes
    de um create (pacote de outro servidor dá 400 "doesn't exists")."""
    init_db()
    servers = client.servers()
    save_raw(f"{BLACKBR_API}/servers", servers)
    packages = client.packages()
    save_raw(f"{BLACKBR_API}/packages/list", packages)
    # O painel real devolve envelope Laravel {"data": [...]} (achado na VPS);
    # aceita lista crua também.
    if isinstance(servers, dict):
        servers = servers.get("data", [])
    if isinstance(packages, dict):
        packages = packages.get("data", [])
    synced = save_entities("blackbr.server", [(s["id"], s) for s in servers if s.get("id")])
    synced += save_entities("blackbr.package", [(p["id"], p) for p in packages if p.get("id")])
    return {"what": "servers_packages", "synced": synced,
            "servers": len(servers), "packages": len(packages), "status": "synced"}


SYNCERS = {
    "customers": sync_customers,
    "expiring": sync_expiring,
    "dashboard": sync_dashboard,
    "resellers": sync_resellers,
    "statistics": sync_statistics,
    "servers_packages": sync_servers_packages,
}


def sync_all(client: BlackbrApiClient, pages: int = 5, per_page: int = 100) -> list[dict]:
    return [sync_customers(client, pages, per_page)] + [
        SYNCERS[name](client)
        for name in ("expiring", "dashboard", "resellers", "statistics", "servers_packages")
    ]


def entities_summary() -> dict:
    """Contagem por kind — para status/monitoramento."""
    init_db()
    kinds = ("blackbr.customer", "blackbr.expiring", "blackbr.dashboard_chart", "blackbr.dashboard_metric",
             "blackbr.reseller", "blackbr.customer_stats", "blackbr.server", "blackbr.package")
    return {k: count_entities(k) for k in kinds}
