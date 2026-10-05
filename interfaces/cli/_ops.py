"""Comandos de operação do FRAMEWORK (genéricos, multi-painel): export,
alerts, doctor, snapshot. Um módulo só — o registro é no cli/__init__.

Estes comandos tocam SÓ o banco local e/ou GETs — nenhuma mutação em
painel. O engine de cada um vive em core/<engine>.py.
"""
import json
from pathlib import Path

import typer

from core import alerts as alerts_engine
from core import doctor as doctor_engine
from core import exports, snapshots


def register(app: typer.Typer):
    @app.command("export")
    def cli_export(
        table: str = typer.Option("panel_entities", "--table",
                                  help="panel_entities | products | raw_snapshots"),
        site: str = typer.Option(None, "--site",
                                 help="Filtro por prefixo de kind (<site>.*)"),
        kind: str = typer.Option(None, "--kind", help="Filtro por kind exato"),
        fmt: str = typer.Option(None, "--format", help="csv | json | xlsx (default: csv)"),
        out: str = typer.Option(None, "--out", help="Arquivo de destino (default: out/export_*.ext)"),
        fields: str = typer.Option(None, "--fields", help="Colunas a exportar, separadas por vírgula"),
        limit: int = typer.Option(None, "--limit", help="Cap de linhas"),
    ):
        """Exporta datasets do banco local para CSV/JSON/XLSX (leitura pura)."""
        try:
            res = exports.export_table(
                table=table, out_path=out, fmt=fmt, kind=kind, site=site,
                fields=[f.strip() for f in fields.split(",")] if fields else None,
                limit=limit,
            )
        except (ValueError, RuntimeError) as e:
            typer.secho(f"✖ {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ {res['rows']} linha(s) → {res['path']}", fg=typer.colors.GREEN)
        typer.secho(f"  formato: {res['format']} | colunas: {', '.join(res['columns'][:12])}"
                    f"{' …' if len(res['columns']) > 12 else ''}",
                    fg=typer.colors.BRIGHT_BLACK)

    # ---- alerts --------------------------------------------------------------
    alerts_app = typer.Typer(help="Motor de alertas declarativos sobre o banco local")

    @alerts_app.command("check")
    def cli_alerts_check(
        rules: str = typer.Option(None, "--rules", help="JSON de regras (default: regras automáticas)"),
        json_out: bool = typer.Option(False, "--json", help="Saída JSON em vez de tabela"),
    ):
        """Avalia as regras e mostra no console — NUNCA envia webhook."""
        hits = alerts_engine.evaluate_rules(_load_rules(rules))
        _print_hits(hits, json_out)
        typer.secho(f"\n{len(hits)} alerta(s). "
                    "(modo check: webhook NÃO é enviado; use alerts run)",
                    fg=typer.colors.BRIGHT_BLACK)

    @alerts_app.command("run")
    def cli_alerts_run(
        rules: str = typer.Option(None, "--rules", help="JSON de regras (default: regras automáticas)"),
        json_out: bool = typer.Option(False, "--json", help="Saída JSON em vez de tabela"),
    ):
        """Avalia as regras, mostra no console e envia webhook se HUB_ALERT_WEBHOOK_URL estiver no ambiente."""
        hits = alerts_engine.evaluate_rules(_load_rules(rules))
        _print_hits(hits, json_out)
        url = alerts_engine.notify_webhook(hits)
        if url:
            typer.secho(f"✔ Webhook enviado: {alerts_engine.WEBHOOK_ENV} → "
                        f"{alerts_engine.mask_url(url)}", fg=typer.colors.GREEN)
        else:
            typer.secho(f"– Sem webhook ({alerts_engine.WEBHOOK_ENV} ausente); "
                        "só console.", fg=typer.colors.BRIGHT_BLACK)

    app.add_typer(alerts_app, name="alerts")

    # ---- snapshot --------------------------------------------------------------
    snap_app = typer.Typer(help="Snapshot do banco local + diff legível (auditoria de escrita)")

    @snap_app.command("before")
    def cli_snapshot_before(
        out: str = typer.Option(None, "--out", help="Arquivo do snapshot (default: out/snapshot-before-*.json)"),
        site: str = typer.Option(None, "--site", help="Só kinds com este prefixo (<site>.*)"),
        kind: str = typer.Option(None, "--kind", help="Só este kind"),
    ):
        """Captura o estado ANTES de qualquer operação de escrita."""
        _do_snapshot_save(None, out, site, kind, label="before")

    @snap_app.command("after")
    def cli_snapshot_after(
        before: str = typer.Argument(..., help="Arquivo do snapshot 'before'"),
        out: str = typer.Option(None, "--out", help="Arquivo do snapshot after (default: out/snapshot-after-*.json)"),
        site: str = typer.Option(None, "--site", help="Só kinds com este prefixo"),
        kind: str = typer.Option(None, "--kind", help="Só este kind"),
    ):
        """Captura o estado DEPOIS e mostra o diff contra o 'before'."""
        _do_snapshot_save(before, out, site, kind, label="after")

    @snap_app.command("diff")
    def cli_snapshot_diff(
        before: str = typer.Argument(...),
        after: str = typer.Argument(...),
    ):
        """Diff legível entre dois snapshots existentes."""
        _print_diff(snapshots.diff_files(before, after))

    app.add_typer(snap_app, name="snapshot")

    # ---- doctor --------------------------------------------------------------
    @app.command("doctor")
    def cli_doctor(
        net: bool = typer.Option(False, "--net", help="Inclui healthcheck de rede (GET puro, um por site)"),
    ):
        """Diagnóstico do ambiente do hub: venv, banco, join, sessões, env, deps — verde/amarelo/vermelho."""
        results = doctor_engine.run_checks(with_net=net)
        _STATUS = {"ok": typer.colors.GREEN, "warn": typer.colors.YELLOW,
                   "fail": typer.colors.RED}
        _GLIFO = {"ok": "✔", "warn": "▲", "fail": "✖"}
        for r in results:
            typer.secho(f"{_GLIFO[r.status]} [{r.status.upper():4s}] {r.name}: "
                        f"{r.detail}", fg=_STATUS[r.status])
        counts = doctor_engine.summary(results)
        typer.secho(f"\n{counts['ok']} ok · {counts['warn']} atenção · {counts['fail']} falha",
                    fg=typer.colors.GREEN if counts["fail"] == 0 else typer.colors.RED)
        raise typer.Exit(1 if counts["fail"] else 0)


# ---- helpers compartilhados dos comandos acima -------------------------------

def _load_rules(path: str | None):
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        typer.secho(f"✖ Regras inválidas ({path}): {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


def _print_hits(hits, json_out: bool):
    if json_out:
        typer.echo(json.dumps(hits, ensure_ascii=False, indent=2))
        return
    if not hits:
        typer.secho("✔ Nenhum alerta.", fg=typer.colors.GREEN)
        return
    for h in hits:
        typer.secho(f"▲ [{h['rule']}] {h['message']}", fg=typer.colors.YELLOW)


def _do_snapshot_save(before: str | None, out: str | None,
                      site: str | None, kind: str | None, label: str):
    try:
        snap, path = snapshots.take_and_save(
            out_path=out, site=site, kind=kind, label=label)
    except (OSError, ValueError) as e:
        typer.secho(f"✖ {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    total = sum(len(ids) for ids in snap["kinds"].values())
    typer.secho(f"✔ Snapshot {label}: {total} entidade(s) em "
                f"{len(snap['kinds'])} kind(s) → {path}", fg=typer.colors.GREEN)
    if before:
        _print_diff(snapshots.diff_files(before, path))


def _print_diff(diff: dict):
    linhas = snapshots.render_diff(diff)
    if not diff["changed_kinds"]:
        typer.secho("✔ Zero divergência.", fg=typer.colors.GREEN)
    else:
        typer.echo(linhas)
