"""
Retry/backoff unificado para chamadas HTTP DE LEITURA (GET) — engine genérico.

Regras (segurança primeiro):
- Só retry em erros TRANSITÓRIOS: 5xx (500/502/503/504), timeout e erro de
  conexão. Backoff exponencial + jitter (evita thundering herd).
- 403/429 = Cloudflare. NUNCA insistir: cada tentativa reforça o score do
  browser e pode banir o IP/sessão. Falha RÁPIDO levantando
  CloudflareBlocked com a dica de fallback browser (padrão FAST_SYNC:
  transporte HTTP → browser).
- MUTAÇÃO NUNCA RE-TENTA (POST/PUT/DELETE): um retry pode duplicar a
  mutação (cliente criado 2x, delete em alvo errado). A integração no
  PanelApiClient cobre só o caminho GET (_request); _mutate fica intocado.

Uso direto (qualquer painel/script):

    from core.http_retry import retry_call, CloudflareBlocked

    resp = retry_call(lambda: session.get(url))  # retorna a resposta final

A `fn` deve retornar um objeto com `.status_code` (requests, curl_cffi,
_BrowserResponse...) ou levantar exceção de rede. Esgotadas as tentativas
em 5xx, devolve a ÚLTIMA resposta (o caller decide — mesmo contrato de
antes da integração); exceção de rede na última tentativa é re-levantada.
"""
from __future__ import annotations

import random
import time
from collections.abc import Callable

# 5xx transitórios que valem retry. 501 (not implemented) e 505 (version)
# NÃO são transitórios — não insistir.
RETRYABLE_STATUSES = frozenset({500, 502, 503, 504})

# Cloudflare: bloqueio/desafio ou rate limit. Falhar rápido SEMPRE.
CF_STATUSES = frozenset({403, 429})

#: Tentativas padrão (1ª + retries). 3 cobre blip de LB sem virar brute-force.
DEFAULT_ATTEMPTS = 3


class CloudflareBlocked(RuntimeError):
    """403/429 do Cloudflare — não insistir; use o fallback browser.

    `status` carrega o código (403 desafio / 429 rate limit) e `url` o alvo.
    """

    def __init__(self, status: int, url: str = ""):
        self.status = status
        self.url = url
        dica = (
            "Cloudflare barrou o transporte HTTP "
            f"(HTTP {status}) — NÃO insistir. Refaça via browser "
            "(open_client_for transport='browser' / relogin <site>-login --save "
            "para renovar cf_clearance)."
        )
        super().__init__(f"{dica} url={url[:200]}" if url else dica)


def _status(resp) -> int | None:
    """Extrai status_code de qualquer resposta duck-typed (None se não tem)."""
    status = getattr(resp, "status_code", None)
    return status if isinstance(status, int) else None


def _is_network_error(exc: Exception) -> bool:
    """Erros de rede/timeout que valem retry (requests, curl_cffi, stdlib)."""
    import requests.exceptions

    if isinstance(exc, (TimeoutError, requests.exceptions.RequestException)):
        return True
    name = type(exc).__name__.lower()
    return any(m in name for m in ("timeout", "connection", "network"))


def backoff_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    """Backoff exponencial + jitter: base*2^attempt com ruído ±25%.

    `attempt` começa em 0 (após a 1ª falha). Cap em `max_delay`.
    """
    delay = min(max_delay, base_delay * (2 ** attempt))
    return delay * random.uniform(0.75, 1.25)


def retry_call(
    fn: Callable,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_statuses: frozenset[int] | set[int] = RETRYABLE_STATUSES,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """Chama `fn()` até `attempts` vezes com backoff exponencial + jitter.

    - 403/429 → CloudflareBlocked NA HORA (zero retry; ver docstring do módulo).
    - 5xx em `retry_statuses` / exceção de rede → retry com backoff.
    - Esgotou em 5xx → devolve a ÚLTIMA resposta (caller valida status).
    - Exceção de rede na última tentativa → re-levanta.
    """
    if attempts < 1:
        raise ValueError(f"attempts deve ser >= 1 (recebido {attempts})")

    last_resp = None
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = fn()
        except Exception as exc:
            if not _is_network_error(exc):
                raise
            last_exc = exc
            last_resp = None
        else:
            status = _status(resp)
            if status in CF_STATUSES:
                raise CloudflareBlocked(status, getattr(resp, "url", "") or "")
            if status is None or status not in retry_statuses:
                return resp  # sucesso (ou status que o caller valida)
            last_resp = resp
            last_exc = None
        if attempt < attempts - 1:  # nunca dorme depois da última
            sleep(backoff_delay(attempt, base_delay, max_delay))

    if last_exc is not None:
        raise last_exc
    assert last_resp is not None
    return last_resp
