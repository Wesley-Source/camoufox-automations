#!/usr/bin/env python
"""Juiz karpathy noturno — ciclo completo de validação por painel.

Painéis: blackbr + lideriptv (sigma). Ops por painel (aprovadas pelo dono
em 04/10/2026): sessão + catálogos + listar clientes + buscar (cliente da
page 1, fluxo real do operador) + criar zz_karpathy_* + renovar(+30d) +
trocar senha + playlist + deletar zz_karpathy_* (verificado, janela 3
páginas) + sync vencimentos.

REGRA DE SEGURANÇA: só toca em entidades zz_karpathy_*; deleção verificada;
requests limitados (painéis reais com >10k clientes — sem scan total por
ciclo); qualquer falha limpa o zz antes de sair.

stdout: EXATAMENTE 1 número (segundos totais, 2 decimais).
stderr: timing por passo (para profiling das otimizações).
"""
import secrets
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # raiz do repo

T0 = time.perf_counter()


def _log(msg: str) -> None:
    print(f"[{time.perf_counter() - T0:7.2f}s] {msg}", file=sys.stderr, flush=True)


def _first_id(seq) -> str:
    """Aceita lista crua ou envelope {'data': [...]} (shape varia por painel)."""
    if isinstance(seq, dict):
        seq = seq.get("data") or []
    if not seq:
        raise RuntimeError("catálogo vazio")
    item = seq[0]
    return item["id"] if isinstance(item, dict) else item


def cycle(site: str) -> float:
    from core.panel_api import (
        customer_new_expiry,
        find_customer,
        search_customers,
        set_expiry_on_payload,
    )

    api = __import__(f"core.{site}.api", fromlist=["open_client"])
    t_panel = time.perf_counter()
    cid = None
    uname = f"zz_karpathy_{int(time.time())}_{site}"
    try:
        with api.open_client() as client:
            pkg_cat = _first_id(client.packages())
            srv_cat = _first_id(client.servers())
            _log(f"{site}: catalogos pkg={pkg_cat} srv={srv_cat}")

            page1 = client.customers(page=1).get("data", [])
            _log(f"{site}: listar page1 ({len(page1)} rows)")
            if page1:
                find_customer(client, str(page1[0].get("id")))  # buscar fluxo real
                _log(f"{site}: buscar page-1 ok")

            # pkg/srv de um cliente REAL da page 1 — combo garantidamente
            # válido (catálogo pode listar pacotes desativados p/ create).
            row0 = page1[0] if page1 else {}
            pkg_id = row0.get("package_id") or pkg_cat
            srv_id = row0.get("server_id") or srv_cat

            pwd = secrets.token_urlsafe(12)
            payload = {
                "username": uname,
                "password": pwd,
                "password_confirmation": pwd,
                "name": uname,
                "email": f"{uname}@local.test",
                "connections": 1,
                "server_id": srv_id,
                "package_id": pkg_id,
            }
            res = client.create_customer(payload)
            row = res.get("data") if isinstance(res, dict) else None
            cid = (row or {}).get("id") or (
                (res.get("data") or {}).get("id") if isinstance(res, dict) else None
            )
            if isinstance(row, dict) and not row.get("id"):
                row = None
            _log(f"{site}: criar id={cid} row_da_resposta={bool(row)}")

            if not row:
                row = find_customer(client, cid)  # fallback (scan; raro)
                _log(f"{site}: fallback find_customer")
            if not row:
                raise RuntimeError(f"{site}: zz criado mas row indisponível")

            ymd = customer_new_expiry(row, add_days=30)
            if ymd:
                pl = dict(row)
                set_expiry_on_payload(row, pl, ymd)
                client.update_customer(cid, pl)
                _log(f"{site}: renovar +30d -> {ymd}")

            pwd2 = secrets.token_urlsafe(12)
            pl = dict(row)
            pl["password"] = pwd2
            pl["password_confirmation"] = pwd2
            client.update_customer(cid, pl)
            _log(f"{site}: trocar senha")

            client.customer_playlist(cid)
            _log(f"{site}: playlist")

            client.delete_customer(cid)
            hits = search_customers(client, uname, max_pages=3)
            if hits:
                raise RuntimeError(f"{site}: zz {cid} AINDA EXISTE após delete")
            cid = None
            _log(f"{site}: deletar+verificado")

            client.customers_expiring()
            _log(f"{site}: sync vencimentos")
    finally:
        if cid is not None:
            try:
                with api.open_client() as client:
                    client.delete_customer(cid)
                    _log(f"{site}: LIMPEZA finally zz={cid}")
            except Exception:
                traceback.print_exc(file=sys.stderr)
    return time.perf_counter() - t_panel


def main() -> int:
    total = 0.0
    for site in ("blackbr", "sigma"):  # sigma = lideriptv
        dt = cycle(site)
        total += dt
        _log(f"{site}: ciclo {dt:.2f}s")
    print(f"{total:.2f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
