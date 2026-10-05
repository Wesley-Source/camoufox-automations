"""Base compartilhada dos scrapers (ELT) — 3 painéis gêmeos (AGENTS.md G5).

Cada sync_* recebe um client já aberto (CLI/MCP abrem com open_client() —
um boot de browser por comando) e grava:
- bruto em raw_snapshots (save_raw)
- cópia limpa em panel_entities com UPSERT (save_entities), kinds prefixados
  por site ('' ou '<site>.').

Todas as chamadas são GET — read-only por construção.

Correção vai no BASE, não nas cópias: core/<site>/scraper.py é só
config (ScraperConfig) + wrappers module-level. Os wrappers re-exportam
save_entities/save_raw/init_db/count_entities do core.database e a base os
resolve via cfg.module em tempo de chamada (late binding) — monkeypatch dos
testes no módulo do site continua funcionando.
"""
from dataclasses import dataclass

BASE_KINDS = ("customer", "expiring", "dashboard_chart", "dashboard_metric",
              "reseller", "customer_stats", "server", "package")
CHARTS = ("new-customers", "customer-retention", "revenue-forecast", "lost-revenue")


@dataclass(frozen=True)
class ScraperConfig:
    name: str                 # 'sigma' | '<site>'
    module: object            # módulo scraper do site (late binding p/ testes)
    kinds_prefix: str = ""    # '' | '<site>.'

    @property
    def api(self):
        return getattr(self.module, f"{self.name.upper()}_API")

    def kind(self, k: str) -> str:
        return f"{self.kinds_prefix}{k}"


def sync_customers(cfg, client, pages: int = 1, per_page: int = 100) -> dict:
    m = cfg.module
    m.init_db()
    synced, page = 0, 1
    pages = max(1, pages)  # pages=0 silenciosamente não sincronizava nada
    for page in range(1, pages + 1):
        data = client.customers(page, per_page)
        m.save_raw(f"{cfg.api}/customers?page={page}", data)
        rows = data["data"]
        # M-baixa: lote único (1 conexão/commit) em vez de 1 por linha.
        synced += m.save_entities(cfg.kind("customer"), [(r["id"], r) for r in rows])
        # CR-23: sem meta.last_page (shape inesperado), só paramos com a
        # página vazia — nunca presumimos que a p1 é a última.
        last_page = data.get("meta", {}).get("last_page")
        if not rows or (last_page is not None and page >= last_page):
            break
    return {"what": "customers", "synced": synced, "pages": page, "status": "synced"}


def sync_expiring(cfg, client) -> dict:
    m = cfg.module
    m.init_db()
    data = client.customers_expiring()
    m.save_raw(f"{cfg.api}/customers/expiring", data)
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
    m.save_entities(cfg.kind("expiring"), pairs)
    return {"what": "expiring", "synced": saved, "status": "synced"}


def sync_dashboard(cfg, client) -> dict:
    m = cfg.module
    m.init_db()
    synced = 0
    for name in CHARTS:
        payload = client.dashboard_chart(name)
        m.save_raw(f"{cfg.api}/dashboard/charts/{name}", payload)
        m.save_entities(cfg.kind("dashboard_chart"), [(name, payload)])
        synced += 1
    payload = client.dashboard_recovery()
    m.save_raw(f"{cfg.api}/dashboard/metrics/recovery", payload)
    m.save_entities(cfg.kind("dashboard_metric"), [("recovery", payload)])
    synced += 1
    return {"what": "dashboard", "synced": synced, "status": "synced"}


def sync_resellers(cfg, client) -> dict:
    m = cfg.module
    m.init_db()
    rows = client.resellers()
    m.save_raw(f"{cfg.api}/resellers/list", rows)
    m.save_entities(cfg.kind("reseller"), [(r["id"], r) for r in rows])
    return {"what": "resellers", "synced": len(rows), "status": "synced"}


def sync_statistics(cfg, client) -> dict:
    m = cfg.module
    m.init_db()
    data = client.customers_statistics()
    m.save_raw(f"{cfg.api}/customers/statistics", data)
    inner = data.get("data", data)
    m.save_entities(cfg.kind("customer_stats"), list(inner.items()))
    return {"what": "statistics", "synced": len(inner), "status": "synced"}


def sync_servers_packages(cfg, client) -> dict:
    """Catálogo de servers + packages — valida o par package↔server antes
    de um create (pacote de outro servidor dá 400 "doesn't exists")."""
    m = cfg.module
    m.init_db()
    servers = client.servers()
    m.save_raw(f"{cfg.api}/servers", servers)
    packages = client.packages()
    m.save_raw(f"{cfg.api}/packages/list", packages)
    # O painel real devolve envelope Laravel {"data": [...]} (achado na VPS);
    # aceita lista crua também.
    if isinstance(servers, dict):
        servers = servers.get("data", [])
    if isinstance(packages, dict):
        packages = packages.get("data", [])
    synced = m.save_entities(cfg.kind("server"), [(s["id"], s) for s in servers if s.get("id")])
    synced += m.save_entities(cfg.kind("package"), [(p["id"], p) for p in packages if p.get("id")])
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


def sync_all(cfg, client, pages: int = 5, per_page: int = 100) -> list[dict]:
    return [sync_customers(cfg, client, pages, per_page)] + [
        SYNCERS[name](cfg, client)
        for name in ("expiring", "dashboard", "resellers", "statistics", "servers_packages")
    ]


def entities_summary(cfg) -> dict:
    """Contagem por kind — para status/monitoramento."""
    m = cfg.module
    m.init_db()
    return {cfg.kind(k): m.count_entities(cfg.kind(k)) for k in BASE_KINDS}
