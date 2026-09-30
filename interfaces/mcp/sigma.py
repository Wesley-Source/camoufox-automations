import json
import os
import secrets

from core.sigma.api import (
    customer_new_expiry,
    find_customer,
    open_client,
    set_expiry_on_payload,
)
from core.sigma.auth import login
from core.sigma.scraper import SYNCERS, entities_summary, sync_all, sync_customers


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
                if o_que == "all":
                    results = sync_all(client, paginas)
                elif o_que == "customers":
                    results = [sync_customers(client, paginas)]
                else:
                    results = [SYNCERS[o_que](client)]
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

    # ---- gestão de clientes (mutações; 4 operações curated, sem bulk) ----------

    @mcp.tool()
    def criar_cliente_sigma(
        username: str,
        package_id: str,
        server_id: str,
        connections: int = 1,
        password: str = None,
    ) -> str:
        """
        Cria um cliente no painel Sigma. package_id e server_id são IDs string
        do painel (ex.: rdqLkQjWAE) e devem formar par coerente (o pacote
        pertence ao servidor). Senha gerada se não informada.
        """
        pwd = password or secrets.token_urlsafe(12)
        payload = {
            "username": username, "password": pwd, "password_confirmation": pwd,
            "name": username, "email": f"{username}@local.test",
            "connections": connections, "server_id": server_id, "package_id": package_id,
        }
        try:
            with open_client() as client:
                res = client.create_customer(payload)
        except Exception as e:
            return f"Create falhou: {e}"
        cid = (res.get("data") or {}).get("id") if isinstance(res, dict) else None
        return json.dumps({"criado": username, "id": cid or "?", "senha": pwd}, ensure_ascii=False)

    @mcp.tool()
    def editar_cliente_sigma(customer_id: str, note: str = None, add_days: int = 0) -> str:
        """
        Edita um cliente do painel Sigma: altera a nota e/ou estende a expiração
        em add_days dias. Ao menos um dos dois deve ser informado.
        """
        if not (note or add_days):
            return "Nada a mudar: informe note e/ou add_days."
        try:
            with open_client() as client:
                row = find_customer(client, customer_id)
                if not row:
                    return f"Cliente {customer_id} não encontrado."
                payload = dict(row)
                if note:
                    payload["note"] = note
                new_exp = None
                if add_days:
                    new_exp = customer_new_expiry(row, add_days)
                    if not new_exp:
                        return "Row sem data de expiração — não dá para estender."
                    set_expiry_on_payload(row, payload, new_exp)
                client.update_customer(customer_id, payload)
        except Exception as e:
            return f"Update falhou: {e}"
        return json.dumps({"id": customer_id, "nota": note, "expira": new_exp}, ensure_ascii=False)

    @mcp.tool()
    def excluir_cliente_sigma(customer_id: str, confirmar: bool = False) -> str:
        """
        Remove um cliente do painel Sigma (SOFT delete, restaurável).
        DESTRUTIVO: exige confirmar=True além do ID correto.
        """
        if not confirmar:
            return "Exclusão exige confirmar=True (soft delete)."
        try:
            with open_client() as client:
                res = client.delete_customer(customer_id)
        except Exception as e:
            return f"Delete falhou: {e}"
        return json.dumps({"id": customer_id, "resposta": res}, ensure_ascii=False)

    @mcp.tool()
    def resync_cliente_sigma(customer_id: str) -> str:
        """Força o resync do cliente no servidor IPTV do painel Sigma."""
        try:
            with open_client() as client:
                res = client.resync_customer(customer_id)
        except Exception as e:
            return f"Resync falhou: {e}"
        return json.dumps({"id": customer_id, "resposta": res}, ensure_ascii=False)
