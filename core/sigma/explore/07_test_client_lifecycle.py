"""
Etapa 7 da exploração do painel Sigma — ciclo de vida do CLIENTE TESTE.

Cria um cliente com nome inconfundível (zz_test_explorer_*), verifica,
edita (renova due_date), faz resync e EXCLUI — descobrindo os payloads
reais de cada endpoint. NENHUM cliente real é tocado, por três camadas:

1. GUARDIÃO DE URL: route handler que aborta qualquer request mutante
   cuja URL não seja exatamente o create (POST /api/customers) ou não
   contenha o ID do cliente teste. Um bug de variável não derruba
   cliente real — a request morre no browser.
2. Nome inconfundível zz_test_explorer_<stamp> em TODAS as buscas.
3. Snapshot antes/depois (lógica do 06) + diff impresso no fim: se
   aparecer qualquer cliente real no diff, o script termina com erro.

Create usa tentativa iterativa: POST vazio → o Laravel responde 422 com
o array `errors` nomeando cada campo obrigatório (descoberta guiada pelo
próprio schema, sem chute).

Saída: out/lifecycle_log.json + diffs no terminal.

Rode: venv/bin/python core/sigma/explore/07_test_client_lifecycle.py
"""
import importlib
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.sigma.api import SigmaApiError, open_client  # noqa: E402
from core.sigma.auth import SIGMA_API  # noqa: E402
from core.sigma.explore._guard import SAFE_METHODS  # noqa: E402

snap = importlib.import_module("core.sigma.explore.06_customers_snapshot")

OUT = Path(__file__).parent / "out"
CREATE_URL = SIGMA_API + "/customers"
TEST_PREFIX = "zz_test_explorer_"
MAX_CREATE_ATTEMPTS = 8
PAGE_EVAL_FETCH = """
async ([u, opts]) => {
  const r = await fetch(u, opts);
  let body = await r.text();
  try { body = JSON.parse(body); } catch {}
  return [r.status, body];
}
"""


class TestIdMissing(Exception):
    pass


def make_guard(state: dict):
    """Route handler: GET passa; mutante só se for o create ou contiver o id do teste."""
    blocked: list = []

    def _route(route):
        req = route.request
        try:
            if req.method.upper() in SAFE_METHODS:
                route.continue_()
                return
            url = req.url
            ok = (
                (req.method.upper() == "POST" and url.rstrip("/") == CREATE_URL)
                or (state.get("test_id") and state["test_id"] in url)
            )
            if ok:
                route.continue_()
            else:
                blocked.append({"method": req.method, "url": url})
                route.abort("blocked-lifecycle-guard")
        except Exception:
            try:
                # CR-09: fail-CLOSED — erro no guardião nunca libera a mutação.
                route.abort("blocked-guard-error")
            except Exception:
                pass

    return _route, blocked


def raw(page, method: str, path: str, payload=None, token: str = ""):
    """fetch cru dentro da página (POST/PUT/DELETE inclusos) → (status, corpo).

    Headers espelham o axios da SPA (Accept + X-Requested-With): sem eles
    o Laravel responde validação com redirect → HTML da SPA (o fetch segue
    o 302 e a gente vê 200 com <!DOCTYPE html> em vez do 422 JSON).
    """
    opts = {
        "method": method,
        "headers": {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Authorization": f"Bearer {token}",
        },
    }
    if payload is not None:
        opts["body"] = json.dumps(payload)
    return page.evaluate(PAGE_EVAL_FETCH, [SIGMA_API + path, opts])


def log_step(log: list, step: str, **kw):
    entry = {"step": step, "ts": datetime.now().isoformat(), **kw}
    log.append(entry)
    typer.echo(f"  · {step}: {json.dumps({k: v for k, v in kw.items()}, ensure_ascii=False)[:160]}")


def as_dict(body):
    """Respostas às vezes vêm como string JSON — normaliza pra dict."""
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}
    return body if isinstance(body, dict) else {"raw": body}


def full_list(client) -> dict:
    """Lista completa id→row com perPage alto (gentil: ~1 request)."""
    customers, page = {}, 1
    while True:
        resp = client._get("/customers", {"page": page, "perPage": 500})
        for row in resp.get("data", []):
            customers[str(row["id"])] = row
        meta = resp.get("meta") or {}
        last = meta.get("last_page", page)
        if page >= last:
            break
        page += 1
        time.sleep(snap.PAGE_DELAY)
    return customers


def list_test_customers(client) -> list:
    """Todos os zz_test_explorer_* — da lista completa (o filtro ?username= não é confiável)."""
    return [r for r in full_list(client).values()
            if str(r.get("username", "")).startswith(TEST_PREFIX)]


def find_test_customer(client, username: str):
    rows = [r for r in full_list(client).values()
            if str(r.get("username", "")) == username]
    return rows[0] if rows else None


def main():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    username = TEST_PREFIX + stamp
    log: list = []
    state: dict = {"test_id": None}

    typer.echo("Abrindo painel + guardião de URL...")
    try:
        with open_client() as client:
            page = client._session._page
            handler, blocked = make_guard(state)
            page.route("**/*", handler)

            # 0) snapshot ANTES (mesmo formato do 06, sem abrir outro browser)
            typer.echo("[0/6] Snapshot antes...")
            before = full_list(client)

            # 0.5) auto-limpeza: leftovers de execuções interrompidas
            leftovers = list_test_customers(client)
            for lr in leftovers:
                lid = str(lr["id"])
                typer.secho(f"  ⚠ leftover {lr.get('username')} (id={lid}) — excluindo...", fg=typer.colors.YELLOW)
                state["test_id"] = lid  # libera o DELETE no guardião
                st, _ = raw(page, "DELETE", f"/customers/{lid}", token=client.token)
                log_step(log, "leftover_cleaned", id=lid, status=st)
            state["test_id"] = None

            # 1) descoberta passiva: servers/packages pra montar o payload
            typer.echo("[1/6] Descobrindo servers/packages (só GET)...")
            server_id = package_id = None
            try:
                st, body = raw(page, "GET", "/servers", token=client.token)
                body = as_dict(body)
                servers = body.get("data", body.get("servers", []))
                st2, body2 = raw(page, "GET", "/packages/list", token=client.token)
                body2 = as_dict(body2)
                packages = body2.get("data", body2.get("packages", []))
                log_step(log, "discover", servers_status=st, n_servers=len(servers),
                         packages_status=st2, n_packages=len(packages))
                # Par coerente: pacote que pertence a um servidor existente
                by_server = {}
                for p in packages:
                    by_server.setdefault(str(p.get("server_id", "")), []).append(p)
                for s in servers:
                    sid = str(s.get("id"))
                    if by_server.get(sid):
                        server_id, package_id = sid, str(by_server[sid][0]["id"])
                        break
                if package_id is None and packages:  # fallback: 1º pacote e o server dele
                    package_id = str(packages[0].get("id"))
                    server_id = str(packages[0].get("server_id")) or server_id
            except Exception as e:
                log_step(log, "discover", error=str(e).splitlines()[0][:80])
            typer.echo(f"  → server_id={server_id} package_id={package_id}")

            # 2) CREATE iterativo — 422 nos ensina o schema
            typer.echo(f"[2/6] Criando {username} (iterativo por validação)...")
            payload = {"username": username}
            status = None
            for attempt in range(1, MAX_CREATE_ATTEMPTS + 1):
                st, body = raw(page, "POST", "/customers", payload, token=client.token)
                body = as_dict(body)
                log_step(log, "create_attempt", n=attempt, status=st,
                         errors=body.get("errors"), body=str(body)[:200])
                if st in (200, 201):
                    status = st
                    # M5: seta test_id do CORPO da resposta ANTES de qualquer
                    # chamada que pode falhar (find pagina tudo) — se cair no
                    # finally com test_id None, o zz_test fica órfão no painel.
                    direct = (body.get("data") or {}).get("id") if isinstance(body, dict) else None
                    if direct:
                        state["test_id"] = str(direct)
                    else:
                        # fallback: resposta sem shape estável — procura na lista
                        created = find_test_customer(client, username)
                        if not created:
                            raise typer.Exit("✖ Create 200 mas cliente não aparece na lista.")
                        state["test_id"] = str(created["id"])
                    typer.secho(f"  ✔ criado id={state['test_id']}", fg=typer.colors.GREEN)
                    break
                errors = body.get("errors")
                typer.echo(f"  {st} → {json.dumps(errors, ensure_ascii=False)[:200]}")
                payload = fill_missing(payload, errors, username, server_id, package_id)
            if state["test_id"] is None:
                raise typer.Exit(f"✖ Create não concluído (último status={status}). Log em out/.")
            test_id = state["test_id"]
            last_payload = dict(payload)

            # 3) VERIFY: aparece na lista pelo username?
            typer.echo("[3/6] Verificando na lista...")
            row = find_test_customer(client, username)
            log_step(log, "verify_created", found=bool(row), id=row.get("id") if row else None)
            if not row or str(row.get("id")) != test_id:
                raise typer.Exit(f"✖ Cliente criado não encontrado na lista (id esperado {test_id}).")

            # 4) EDIT/RENEW: estende due_date em +1 mês e muda a note
            typer.echo("[4/6] Editando (renova due_date + note)...")
            edit = dict(last_payload)
            base = row.get("expiry_date") or row.get("due_date")
            try:
                new_due = (datetime.fromisoformat(str(base).replace("Z", "+00:00")) + timedelta(days=30)).date().isoformat()
            except ValueError:
                new_due = (datetime.now() + timedelta(days=30)).date().isoformat()
            edit.update({"note": f"editado pelo explorer {stamp}", "expiry_date": new_due, "due_date": new_due})
            st, body = raw(page, "PUT", f"/customers/{test_id}", edit, token=client.token)
            log_step(log, "edit", status=st, errors=body.get("errors") if isinstance(body, dict) else None)
            row2 = find_test_customer(client, username)
            applied = bool(row2) and (row2.get("note") == edit["note"])
            log_step(log, "verify_edit", status=st, note_applied=applied)

            # 5) RESYNC (empurra pro servidor de stream — só o teste)
            typer.echo("[5/6] Resync do teste...")
            st, body = raw(page, "POST", f"/customers/{test_id}/resync", {}, token=client.token)
            log_step(log, "resync", status=st)

            # 6) DELETE + verificação de ausência
            typer.echo("[6/6] Excluindo o teste...")
            st, body = raw(page, "DELETE", f"/customers/{test_id}", token=client.token)
            log_step(log, "delete", status=st, body=str(body)[:120])
            gone = find_test_customer(client, username) is None
            log_step(log, "verify_deleted", gone=gone)
            state["test_id"] = None  # deletado OK — cleanup emergencial vira no-op

            # Snapshot DEPOIS + diff — o veredito
            typer.echo("Snapshot depois + diff...")
            after = full_list(client)
            d = snap.diff(before, after)

            (OUT / "lifecycle_log.json").write_text(
                json.dumps({"log": log, "diff": d, "blocked": blocked},
                           indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            snap.show_diff(d)

            clean = (
                set(d["added"]) <= {test_id}
                and set(d["removed"]) == set()
                and set(d["changed"]) == set()
            )
            if not gone or not clean:
                typer.secho("✖ DIVERGÊNCIA: diff mostra mudanças fora do ciclo teste!", fg=typer.colors.RED)
                raise typer.Exit(1)
            typer.secho("✔ Ciclo completo: criou, editou, resincronizou e excluiu — zero impacto real.", fg=typer.colors.GREEN)
            if blocked:
                typer.secho(f"⚠ Guardião bloqueou {len(blocked)} request(s): {blocked[:5]}", fg=typer.colors.YELLOW)
    finally:
        # CR-29: crash no meio do ciclo não pode deixar zz_test_* no painel.
        tid = state.get("test_id")
        if tid:
            try:
                # A3: cleanup emergencial com allowlist do próprio make_guard
                handler2, _ = make_guard(state)
                with open_client(guard=handler2) as c2:
                    st, _ = raw(c2._session._page, "DELETE",
                                f"/customers/{tid}", token=c2.token)
                typer.secho(f"⚠ Cleanup emergencial: {tid} excluído (status {st}).",
                            fg=typer.colors.YELLOW)
            except Exception as e:
                typer.secho(f"✖ Cleanup emergencial FALHOU p/ {tid}: {e} — "
                            "remova o cliente teste manualmente.", fg=typer.colors.RED)



def fill_missing(payload: dict, errors, username: str, server_id, package_id) -> dict:
    """Preenche campos a partir do array de erros do Laravel."""
    text = json.dumps(errors, ensure_ascii=False).lower() if errors else ""
    p = dict(payload)
    p.setdefault("password", "ZzTest-2026x")
    p.setdefault("password_confirmation", "ZzTest-2026x")
    p.setdefault("email", f"{username}@example.invalid")
    p.setdefault("name", username)
    p.setdefault("connections", 1)
    if "server" in text and server_id:
        p.setdefault("server_id", server_id)
    if "package" in text and package_id:
        p.setdefault("package_id", package_id)
    if "date" in text:
        p.setdefault("expiry_date", (datetime.now() + timedelta(days=30)).date().isoformat())
    return p


if __name__ == "__main__":
    main()
