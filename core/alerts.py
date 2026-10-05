"""
Motor de alertas declarativos sobre o banco local — engine genérico.

Regras checam `panel_entities` e produzem HITS (dicts) — nada é enviado
sem que o chamador peça. Três tipos de regra (qualquer painel/site):

  expiring_within  — entidades de um kind vencendo em N dias
                     (lê expires_at/expiry_date/due_date com a convenção
                     UTC-3 do painel, via panel_api.customer_new_expiry)
  stale_sync       — kind sem sync há mais de N horas (updated_at velho)
  count_below      — kind com menos de N entidades (ex.: sync veio vazio)

Console SEMPRE; webhook SOMENTE em `alerts run` e só se
HUB_ALERT_WEBHOOK_URL estiver no ambiente (`alerts check` NUNCA envia).
Payload do webhook: JSON {source, sent_at, total, alerts} — hits carregam
só projeção segura (project_customer / ids), NUNCA password/m3u_url.

Regras custom: JSON via --rules
  [{"type": "expiring_within", "kind": "blackbr.customer", "days": 3},
   {"type": "stale_sync", "kind": "blackbr.customer", "hours": 24},
   {"type": "count_below", "kind": "blackbr.customer", "threshold": 10}]
Sem --rules: regras automáticas descobertas dos kinds existentes no banco.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from contextlib import contextmanager

import requests

from core import database
from core.panel_api import customer_new_expiry, project_customer

WEBHOOK_ENV = "HUB_ALERT_WEBHOOK_URL"

#: Kinds de "cliente" por sufixo/prefixo legado (regras automáticas)
_CUSTOMER_SUFFIX = ".customer"
_LEGACY_CUSTOMER = "customer"

RULE_TYPES = ("expiring_within", "stale_sync", "count_below")


@contextmanager
def _connect(db_path: str | None):
    conn = sqlite3.connect(db_path or database.DB_PATH, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def _kinds(db_path: str | None = None) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT kind FROM panel_entities ORDER BY kind").fetchall()
    return [r[0] for r in rows]


def default_rules(db_path: str | None = None) -> list[dict]:
    """Regras automáticas a partir dos kinds presentes no banco:
    clientes → vencendo em 7 dias + sync vazio; todo kind → sync > 48h."""
    rules: list[dict] = []
    for kind in _kinds(db_path):
        is_customer = (kind.endswith(_CUSTOMER_SUFFIX)
                       or kind == _LEGACY_CUSTOMER)
        if is_customer:
            rules.append({"type": "expiring_within", "kind": kind, "days": 7})
            rules.append({"type": "count_below", "kind": kind, "threshold": 1})
        rules.append({"type": "stale_sync", "kind": kind, "hours": 48})
    return rules


def validate_rules(rules: list[dict]) -> list[dict]:
    """Valida schema das regras cedo (errar na carga, não na avaliação)."""
    out = []
    for i, r in enumerate(rules):
        if not isinstance(r, dict) or r.get("type") not in RULE_TYPES:
            raise ValueError(
                f"regra[{i}]: type deve ser um de {', '.join(RULE_TYPES)} "
                f"(recebido {r.get('type')!r})")
        if not r.get("kind"):
            raise ValueError(f"regra[{i}]: 'kind' é obrigatório")
        if r["type"] == "expiring_within" and int(r.get("days", 7)) < 0:
            raise ValueError(f"regra[{i}]: days >= 0")
        if r["type"] == "stale_sync" and float(r.get("hours", 48)) < 0:
            raise ValueError(f"regra[{i}]: hours >= 0")
        if r["type"] == "count_below" and int(r.get("threshold", 1)) < 0:
            raise ValueError(f"regra[{i}]: threshold >= 0")
        out.append(r)
    return out


def _hit(rule: dict, message: str, count: int, sample: list) -> dict:
    return {
        "rule": rule.get("id") or f"{rule['type']}/{rule['kind']}",
        "type": rule["type"],
        "kind": rule["kind"],
        "message": message,
        "count": count,
        "sample": sample,
    }


def _sample_for(kind: str, rows: list[dict], n: int = 5) -> list[dict]:
    """Projeção SEGURA dos primeiros n (customers via allowlist; resto, id)."""
    if kind.endswith(_CUSTOMER_SUFFIX) or kind == _LEGACY_CUSTOMER:
        return [project_customer(r) for r in rows[:n]]
    return [{"id": r["id"]} for r in rows[:n]]


def evaluate_rules(rules: list[dict] | None = None,
                   db_path: str | None = None,
                   now: _dt.datetime | None = None) -> list[dict]:
    """Avalia as regras contra o banco local; devolve só os hits (sem ruído)."""
    rules = validate_rules(rules if rules is not None else default_rules(db_path))
    now = now or _dt.datetime.now()
    hits: list[dict] = []

    for rule in rules:
        kind = rule["kind"]
        rows = database.all_entities(kind) if not db_path else _entities_of(db_path, kind)

        if rule["type"] == "count_below":
            threshold = int(rule.get("threshold", 1))
            if len(rows) < threshold:
                hits.append(_hit(rule, f"{kind}: {len(rows)} entidade(s) "
                                       f"(mínimo esperado {threshold})",
                                 len(rows), _sample_for(kind, rows)))
            continue

        if rule["type"] == "stale_sync":
            hours = float(rule.get("hours", 48))
            if not rows:
                hits.append(_hit(rule, f"{kind}: nenhuma entidade (nunca sincronizado?)",
                                 0, []))
                continue
            try:
                newest = max(r["_updated_at"] or "" for r in rows)
                age_h = (now - _dt.datetime.fromisoformat(newest)).total_seconds() / 3600
            except (ValueError, TypeError):
                age_h = float("inf")
            if age_h > hours:
                hits.append(_hit(rule, f"{kind}: último sync há {age_h:.0f}h "
                                       f"(limite {hours:.0f}h)",
                                 len(rows), _sample_for(kind, rows)))
            continue

        # expiring_within
        days = int(rule.get("days", 7))
        limite = now + _dt.timedelta(days=days)
        vencendo = []
        for r in rows:
            try:
                ymd = customer_new_expiry(r)
                if not ymd:
                    continue
                venc = _dt.datetime.strptime(ymd, "%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            if now <= venc <= limite:
                vencendo.append(r)
        if vencendo:
            vencendo.sort(key=lambda r: customer_new_expiry(r) or "")
            hits.append(_hit(rule, f"{kind}: {len(vencendo)} cliente(s) "
                                   f"vencendo em <= {days} dia(s)",
                             len(vencendo), _sample_for(kind, vencendo)))
    return hits


def _entities_of(db_path: str, kind: str) -> list[dict]:
    """all_entities contra um banco alternativo (testes)."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT external_id, payload, updated_at FROM panel_entities "
            "WHERE kind = ? ORDER BY external_id", (kind,)).fetchall()
    return database._rows_to_entities(rows)


def mask_url(url: str) -> str:
    """Webhook nunca aparece inteiro no console (tokens moram na URL)."""
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.hostname}/…"


def notify_webhook(hits: list[dict], url: str | None = None,
                   timeout: float = 10.0) -> str | None:
    """POST JSON dos hits no webhook genérico. Env HUB_ALERT_WEBHOOK_URL.

    Devolve a URL se enviou; None se o env não existe. Falha de rede/
    HTTP levanta (o CLI mostra) — silenciar alerta seria pior.
    """
    if not hits:
        return None
    url = url or os.environ.get(WEBHOOK_ENV)
    if not url:
        return None
    payload = {
        "source": "camoufox-automations",
        "sent_at": _dt.datetime.now().isoformat(),
        "total": len(hits),
        "alerts": hits,
    }
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return url
