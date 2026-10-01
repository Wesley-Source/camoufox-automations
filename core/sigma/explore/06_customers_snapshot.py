"""
Snapshot completo dos clientes do painel — SEM gravar nada no banco.

Busca todas as páginas de /api/customers (só GET) e salva um JSON com
todos os clientes, indexados por id, em out/snapshots/.

Se já existir um snapshot anterior, imprime o DIFF: clientes adicionados,
removidos e alterados (campo a campo). É a prova auditável de que a
exploração de CRUD não mexeu em nenhum cliente real: rode antes e depois.

Snapshots ficam em out/ (gitignored — contêm PII).

Rode: venv/bin/python core/sigma/explore/06_customers_snapshot.py [--compare caminho.json]
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.sigma.api import open_client  # noqa: E402
from core.sigma.explore._guard import install_guard  # noqa: E402

OUT = Path(__file__).parent / "out" / "snapshots"
PAGE_DELAY = 0.4  # s entre páginas — gentle com o painel


def fetch_all(client) -> dict:
    """Todas as páginas de customers, indexadas por id."""
    customers, page = {}, 1
    while True:
        resp = client.customers(page)
        for row in resp.get("data", []):
            customers[str(row["id"])] = row
        meta = resp.get("meta") or {}
        last = meta.get("last_page", page)
        if page >= last:
            break
        page += 1
        time.sleep(PAGE_DELAY)
    return customers


def diff(old: dict, new: dict) -> dict:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = {}
    for cid in sorted(set(old) & set(new)):
        fields = {
            k for k in set(old[cid]) | set(new[cid])
            if old[cid].get(k) != new[cid].get(k)
        }
        if fields:
            changed[cid] = sorted(fields)
    return {"added": added, "removed": removed, "changed": changed}


def show_diff(d: dict):
    typer.echo(f"  adicionados: {len(d['added'])} | removidos: {len(d['removed'])} | alterados: {len(d['changed'])}")
    for cid in d["added"][:10]:
        typer.secho(f"  + {cid}", fg=typer.colors.GREEN)
    for cid in d["removed"][:10]:
        typer.secho(f"  - {cid}", fg=typer.colors.RED)
    for cid, fields in list(d["changed"].items())[:10]:
        typer.secho(f"  ~ {cid}: {', '.join(fields)}", fg=typer.colors.YELLOW)
    if d["added"] or d["removed"] or d["changed"]:
        typer.secho("⚠ DIVERGÊNCIA DETECTADA — investigue antes de prosseguir.", fg=typer.colors.RED)
    else:
        typer.secho("✔ Nenhum cliente real mudou desde o snapshot anterior.", fg=typer.colors.GREEN)


def main(
    compare: Path = typer.Option(None, help="Snapshot anterior p/ diff (default: o mais recente)."),
):
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = OUT / f"customers_{stamp}.json"

    typer.echo("Baixando TODOS os clientes do painel (só GET, sem tocar no banco)...")
    with open_client(guard=install_guard) as client:
        customers = fetch_all(client)

    payload = {
        "timestamp": stamp,
        "total": len(customers),
        "customers": customers,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.secho(f"✔ {len(customers)} clientes → {target}", fg=typer.colors.GREEN)

    prev = compare
    if prev is None:
        older = sorted(p for p in OUT.glob("customers_*.json") if p != target)
        prev = older[-1] if older else None
    if prev and prev.exists():
        typer.echo(f"\nDiff vs {prev.name}:")
        old = json.loads(prev.read_text(encoding="utf-8"))["customers"]
        show_diff(diff(old, customers))
    elif not prev:
        typer.echo("(primeiro snapshot — baseline criado; rode de novo depois do CRUD p/ diff)")


if __name__ == "__main__":
    typer.run(main)  # main() direto não processa typer.Option (bug já visto no 03)
