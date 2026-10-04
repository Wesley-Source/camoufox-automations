"""
Client HTTP do Rocket Gestor (app.rocketgestor.com — Django server-rendered).

Diferente dos painéis Sigma: sessão é COOKIES (sessionid/csrftoken), não
Bearer/localStorage. `requests` puro resolve todos os GETs (sem challenge de
CF em GET) e os POSTs levam o token do formulário (csrfmiddlewaretoken) +
header Referer (Django valida em HTTPS).

Política do painel (decisão do dono): créditos INEXISTENTES — criar/alterar/
deletar CLIENTES DE TESTE (`zz_test_*`) é livre; clientes reais intocados.

Delete de cliente = soft (vai pra lixeira /gerenciador/clientes/lixeira/,
restaurável). Edição REUSA a rota de criação: POST /gerenciador/cliente/add
com o campo hidden `teste_id` vazio = cria, preenchido = atualiza.
"""
import re
import time
from contextlib import contextmanager

import requests

from core.database import save_entities
from core.rocketgestor.auth import (
    ROCKET_URL,
    ROCKET_SESSION_FILE,
    load_session,
)

_CLIENTES = "/gerenciador/clientes/"
_ADD = "/gerenciador/cliente/add"
_MASS_DELETE = "/gerenciador/clientes/deletar-em-massa/"

_ROW_RE = re.compile(r'<tr class="cliente-row".*?</tr>', re.S)
_CSRF_RE = re.compile(r'csrfmiddlewaretoken" value="([^"]+)"')
_COPY_RE = re.compile(r"copy\('([^']*)'\)")
_TAG_RE = re.compile(r"<[^>]+>")


class RocketGestorError(RuntimeError):
    """Falha de request/parse do Rocket Gestor (vendor=rocketgestor)."""


def _txt(fragment: str) -> str:
    """HTML → texto limpo (tags fora, espaços colapsados)."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", fragment)).strip()


def _parse_row(row_html: str) -> dict:
    """Uma <tr class='cliente-row'> → dict do cliente."""
    tds = re.findall(r"<td.*?</td>", row_html, re.S)
    cid = (re.search(r'data-cliente-id="([^"]+)"', row_html) or [None, ""])[1]
    uuid_m = re.search(r"/gerenciador/cliente/info/([0-9a-f-]{36})/", row_html)
    nome_m = re.search(r'data-bs-title="([^"]*)"', row_html)
    copies = [c.replace("\\u002D", "-") for c in _COPY_RE.findall(row_html)]
    # copies[0]=login IPTV, [1]=telefone, [2]=vencimento (arg exato do copy();
    # o HTML escapa o hífen como \u002D literal)
    login = copies[0] if copies else ""
    telefone = copies[1] if len(copies) > 1 else ""
    vencimento = copies[2] if len(copies) > 2 else ""
    plain = [_txt(td) for td in tds]
    # plain: 0 checkbox, 1 nome, 2 telefone, 3 vencimento, 4 plano, 5 valor,
    # 6 status, 7 servidor, 8 telas, 9 aplicativo, 10 dispositivo,
    # 11 captação, 12 tipo, 13 pendência, 14 ações
    return {
        "id": cid,
        "info_url": f"/gerenciador/cliente/info/{uuid_m.group(1)}/" if uuid_m else "",
        "uuid": uuid_m.group(1) if uuid_m else "",
        "nome": (nome_m.group(1) if nome_m else (plain[1] if len(plain) > 1 else "")),
        "login": login,
        "telefone": telefone,
        "vencimento": vencimento,
        "plano": plain[4] if len(plain) > 4 else "",
        "valor": plain[5] if len(plain) > 5 else "",
        "status": plain[6] if len(plain) > 6 else "",
        "servidor": plain[7] if len(plain) > 7 else "",
        "telas": plain[8] if len(plain) > 8 else "",
        "aplicativo": plain[9] if len(plain) > 9 else "",
        "dispositivo": plain[10] if len(plain) > 10 else "",
        "captacao": plain[11] if len(plain) > 11 else "",
        "tipo": plain[12] if len(plain) > 12 else "",
        "pendencia": plain[13] if len(plain) > 13 else "",
    }


class RocketGestorClient:
    """Operações de /gerenciador/ via requests (cookies do session json)."""

    VENDOR = "rocketgestor"

    def __init__(self, session: requests.Session):
        self.s = session

    # ---- baixo nível -------------------------------------------------------

    def _get(self, path: str, **kw) -> str:
        r = self.s.get(f"{ROCKET_URL}{path}", timeout=30, **kw)
        if r.status_code != 200:
            raise RocketGestorError(f"GET {path} -> {r.status_code}")
        return r.text

    def _post(self, path: str, data: dict, referer: str = "/gerenciador/clientes/") -> requests.Response:
        """POST com CSRF (header X-CSRFToken = cookie csrftoken) + Referer."""
        token = self.s.cookies.get("csrftoken") or self._csrf_from(_CLIENTES)
        headers = {
            "Referer": f"{ROCKET_URL}{referer}",
            "X-CSRFToken": token or "",
        }
        r = self.s.post(f"{ROCKET_URL}{path}", data=data, headers=headers, timeout=30)
        if r.status_code >= 400:
            raise RocketGestorError(f"POST {path} -> {r.status_code}: {r.text[:200]}")
        return r

    def _csrf_from(self, path: str) -> str:
        m = _CSRF_RE.search(self._get(path))
        return m.group(1) if m else ""

    # ---- leitura -----------------------------------------------------------

    def list_clients(self, status: str = None, max_pages: int = 50) -> list:
        """Página(s) de clientes parseadas (regex — a TR tem data-cliente-id)."""
        out, seen, page = [], set(), 1
        base = _CLIENTES + (f"?status={status}" if status else "")
        while page <= max_pages:
            sep = "&" if "?" in base else "?"
            html = self._get(f"{base}{sep}page={page}")
            new = [r for r in ( _parse_row(m) for m in _ROW_RE.findall(html) ) if r["id"] and r["id"] not in seen]
            if not new:
                break
            for r in new:
                seen.add(r["id"])
            out.extend(new)
            page += 1
            time.sleep(0.3)  # pacing — regra 6 (sem rajada)
        return out

    def find_client(self, termo: str, status: str = None) -> list:
        """Filtro client-side por nome/login/telefone/id."""
        termo = (termo or "").strip().lower()
        rows = self.list_clients(status=status)
        return [
            r for r in rows
            if termo in (r["nome"] or "").lower()
            or termo in (r["login"] or "").lower()
            or termo in (r["telefone"] or "").lower()
            or termo == r["id"]
        ]

    # ---- CRUD (teste-friendly: zz_test_* livres, reais intocados) ----------

    def _alert(self, r):
        """Primeiro alert-danger do corpo (Django re-renderiza 200 em erro)."""
        m = re.search(r"alert-danger[^>]*>\s*(?:<i[^>]*></i>\s*)?([^<]{5,300})", r.text)
        return m.group(1).strip() if m else None

    def option_id(self, label: str) -> str:
        """ID numérico de um select (plano/forma/etc.) a partir do texto."""
        page = self._get(_CLIENTES)
        m = re.search(r'<option value="(\d+)"[^>]*>\s*' + re.escape(label), page, re.I)
        if not m:
            raise RocketGestorError(f"Opção '{label}' não achada nos selects do painel.")
        return m.group(1)

    def create_client(self, payload: dict) -> dict:
        """POST /gerenciador/cliente/add com teste_id vazio (cria)."""
        data = {"teste_id": "", "csrfmiddlewaretoken": self._csrf_from(_CLIENTES), **payload}
        for k in ("plano", "forma_de_pagamento"):
            v = data.get(k)
            if v and not str(v).isdigit():
                data[k] = self.option_id(str(v))
        r = self._post(_ADD, data)
        alert = self._alert(r)
        return {"ok": not alert, "status": r.status_code,
                "username": payload.get("usuario", ""), "alert": alert}

    def update_client(self, cliente_id: str, overrides: dict) -> dict:
        """POST /gerenciador/cliente/editar?cliente_id={id} (rota real da UI).

        A UI seta a action do form via JS — sem isso o backend trata como
        create e falha com 'usuario: Já existe'."""
        row = next((r for r in self.list_clients() if r["id"] == str(cliente_id)), None)
        if not row:
            raise RocketGestorError(f"Cliente {cliente_id} não encontrado na lista.")
        # vencimento da row 'dd/mm/yyyy - HH:MM' → ISO p/ input[type=date]
        d, _, hms = row["vencimento"].partition(" - ")
        dd, mm, yy = (d.split("/") + ["", "", ""])[:3]
        iso = "-".join(p for p in (yy, mm, dd) if p)
        tel = re.sub(r"\D", "", row["telefone"])
        tel_fmt = f"{tel[2:4]} {tel[4:9]}-{tel[9:]}" if len(tel) >= 11 else row["telefone"]
        info = self._get(row["info_url"].replace("https://app.rocketgestor.com", ""))
        plano = row["plano"]
        if plano and not plano.isdigit():
            m = re.search(r'<option value="(\d+)"[^>]*>\s*' + re.escape(plano), info, re.I)
            plano = m.group(1) if m else plano
        forma = overrides.get("forma_de_pagamento", "")
        if forma and not str(forma).isdigit():
            fm = re.search(r'<option value="(\d+)"[^>]*>\s*' + re.escape(str(forma)), info, re.I)
            overrides["forma_de_pagamento"] = fm.group(1) if fm else forma
        csrf = (re.search(r'csrfmiddlewaretoken" value="([^"]+)"', info) or [None, ""])[1]
        data = {
            "nome": row["nome"], "usuario": row["login"], "senha": "",
            "painel_id": "", "telefone_0": "BR", "telefone_1": tel_fmt,
            "telefone_secundario_0": "BR", "telefone_secundario_1": "",
            "vencimento": iso, "hora_vencimento": (hms.strip() or "23:59"),
            "email": "", "observacao": "", "servidor": "",
            "plano": plano, "valor": row["valor"].replace("R$ ", "").replace(",", "."),
            "forma_de_pagamento": "", "telas": row["telas"],
            "pix": "", "renew_url": "", "pontos_fidelidade": "0.0",
            "captacao": "", "indicado_por": "", "dispositivo": "", "aplicativo": "",
            "vencimento_aplicativo": "", "mac": "", "device_key_or_OTP_code": "",
            "link_m3u": "", "time": "", "tipo_cliente": "", "aniversario": "",
            "nao_receber_mensagem_ate": "",
            **overrides,
            "csrfmiddlewaretoken": csrf,
        }
        r = self._post(f"/gerenciador/cliente/editar?cliente_id={cliente_id}", data)
        alert = self._alert(r)
        return {"ok": not alert, "id": str(cliente_id), "status": r.status_code, "alert": alert}

    def delete_client(self, cliente_id: str) -> dict:
        """GET /gerenciador/cliente/delete?cliente_id={uuid} (soft → lixeira).

        A view costuma responder 500 DEPOIS de deletar — na dúvida, confirma
        na info page (404 = deletado)."""
        row = next((r for r in self.list_clients() if r["id"] == str(cliente_id)), None)
        if not row or not row["uuid"]:
            raise RocketGestorError(f"Cliente {cliente_id} não encontrado na lista.")
        try:
            r = self._get(f"/gerenciador/cliente/delete?cliente_id={row['uuid']}")
            alert = self._alert(r)
            return {"ok": not alert, "id": str(cliente_id), "uuid": row["uuid"],
                    "status": r.status_code, "alert": alert}
        except RocketGestorError as e:
            if "500" not in str(e):
                raise
            # soft delete: info page continua acessível — a verdade é a lixeira
            lixeira = self._get("/gerenciador/clientes/lixeira/")
            deletado = row["login"] in lixeira or row["nome"] in lixeira
            return {"ok": deletado, "id": str(cliente_id), "uuid": row["uuid"],
                    "alert": None if deletado else f"500 no delete e cliente não está na lixeira: {e}",
                    "note": "500 conhecido da view (deleta e depois quebra) — verificado na lixeira"}

    # ---- sync --------------------------------------------------------------

    def sync_clients(self, status: str = None, max_pages: int = 35) -> dict:
        """Espelha clientes em kinds rocketgestor.client (banco local)."""
        rows = self.list_clients(status=status, max_pages=max_pages)
        synced = save_entities(
            "rocketgestor.client",
            [(r["id"], r) for r in rows],
        )
        return {"what": "clients", "synced": synced, "pages": max_pages}


@contextmanager
def open_client(session_path: str = None, proxy: str = None, guard=None):
    """Client com cookies do session json (requests — sem browser)."""
    sess_data = load_session(session_path or ROCKET_SESSION_FILE)
    if not sess_data:
        raise RuntimeError(
            "Sem sessão rocketgestor — rode: main.py rocketgestor-login --save"
        )
    s = requests.Session()
    for c in sess_data.get("cookies") or []:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", "app.rocketgestor.com"))
    yield RocketGestorClient(s)
