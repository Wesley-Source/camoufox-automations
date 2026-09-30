import json
import os

from core.sigma.api import open_client
from core.sigma.auth import login
from core.sigma.scraper import SYNCERS, entities_summary, sync_all


def register(mcp):
    @mcp.tool()
    def login_sigma() -> str:
        """
        Faz login no painel Sigma (https://lideriptv.sigma.st) e retorna o token de acesso.
        Usa as variáveis de ambiente SIGMA_USERNAME e SIGMA_PASSWORD.
        """
        username = os.environ.get("SIGMA_USERNAME")
        password = os.environ.get("SIGMA_PASSWORD")
        if not username or not password:
            return "Erro: defina SIGMA_USERNAME e SIGMA_PASSWORD no ambiente."
        try:
            sess = login(username, password)
        except Exception as e:
            return f"Login Sigma falhou: {e}"
        return f"Token Sigma: {sess['token']}"

    @mcp.tool()
    def sincronizar_sigma(o_que: str, paginas: int = 5) -> str:
        """
        Sincroniza dados do painel Sigma para o banco local (somente leitura).
        o_que: customers | expiring | dashboard | resellers | statistics | all.
        paginas: páginas de clientes quando aplicável.
        """
        if o_que not in (*SYNCERS, "all"):
            return f"'o_que' inválido: {o_que}. Opções: {', '.join([*SYNCERS, 'all'])}"
        try:
            with open_client() as client:
                results = sync_all(client, paginas) if o_que == "all" else [SYNCERS[o_que](client, paginas)]
        except Exception as e:
            return f"Sync Sigma falhou: {e}"
        return json.dumps(results, ensure_ascii=False)

    @mcp.tool()
    def status_sigma() -> str:
        """
        Valide o acesso ao painel Sigma: usuário, expiração do painel
        (None = ilimitado) e contagem de entidades no banco local.
        """
        try:
            with open_client() as client:
                me = client.me()
        except Exception as e:
            return f"Sigma inacessível: {e}"
        return json.dumps(
            {
                "usuario": me.get("username"),
                "painel_expira_em": me.get("membership_expiry_date") or "ilimitado",
                "banco_local": entities_summary(),
            },
            ensure_ascii=False,
        )
