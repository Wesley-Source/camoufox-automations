import os

from core.sigma.auth import login


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
