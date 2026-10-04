"""Paridade estrutural CLI/MCP entre os 4 painéis sigma-family.

Gate contra regressão da refactor _panel (AGENTS.md G5): todo site deve
expor a MESMA superfície pública — 10 comandos CLI, 12 tools MCP, workers
chamáveis no módulo e SyncWhat cobrindo os SYNCERS do scraper + "all".
"""
from typing import get_args

from interfaces.cli import cli_app
from interfaces.mcp import blackbr, newmais, sigma, woodcine
from interfaces.mcp.server import mcp_app

SITES = {
    "blackbr": blackbr,
    "sigma": sigma,
    "woodcine": woodcine,
    "newmais": newmais,
}
CLI_SUFFIXES = [
    "-account", "-login", "-sync", "-status", "-customer-create",
    "-customer-update", "-customer-delete", "-customer-resync",
    "-customer-playlist", "-servers-packages",
]
MCP_OPS = [
    "login", "sincronizar", "status", "listar_contas", "trocar_conta",
    "listar_pacotes", "buscar_cliente", "listar_clientes",
    "criar_cliente", "editar_cliente", "excluir_cliente", "resync_cliente",
]


def _cli_names() -> set[str]:
    return {c.name for c in cli_app.registered_commands}


def _mcp_names() -> set[str]:
    tools = mcp_app._tool_manager._tools
    return {t.name if hasattr(t, "name") else str(t) for t in tools}


def test_cli_10_comandos_por_site():
    names = _cli_names()
    for site in SITES:
        for suf in CLI_SUFFIXES:
            assert f"{site}{suf}" in names, f"comando {site}{suf} sumiu"


def test_mcp_12_tools_por_site():
    names = _mcp_names()
    for site in SITES:
        for op in MCP_OPS:
            assert f"{op}_{site}" in names, f"tool {op}_{site} sumiu"


def test_workers_chamaveis_no_modulo_do_site():
    for site, mod in SITES.items():
        for op in MCP_OPS:
            w = getattr(mod, f"_{op}_{site}")
            assert callable(w), f"worker _{op}_{site} não é chamável"


def test_syncwhat_cobre_syncers_e_all():
    for site, mod in SITES.items():
        esperado = {*getattr(mod, "SYNCERS"), "all"}
        assert set(get_args(mod.SyncWhat)) == esperado, f"SyncWhat do {site} divergiu"
