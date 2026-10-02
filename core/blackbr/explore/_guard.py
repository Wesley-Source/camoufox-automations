"""
Rede de segurança dos scripts de exploração do painel Blackbr.

Delegado para core/guard.py (fonte única — REGRA DO PROJETO, ver AGENTS.md).
Este módulo continua existindo para os imports existentes dos exploradores.
"""
from core.guard import SAFE_METHODS, install_guard, report_blocked  # noqa: F401
