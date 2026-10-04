"""API do Rocket Gestor — parser da tabela, rotas e payloads (offline)."""
import json

import pytest

import core.rocketgestor.api as rocket


ROW = (
    '<tr class="cliente-row" data-cliente-id="1613748">'
    '<td><input type="checkbox" name="clientes" value="1613748" class="cliente-checkbox"></td>'
    "<td><a class=\"cliente-nome-truncate\" href='/gerenciador/cliente/info/"
    "01a104cf-fa66-788a-b7c3-7c272ada0aa8/' data-bs-title=\"Zz_Test_Probe\">"
    "Zz_Test_Probe <span onclick=\"copy('zztestp4')\">zztestp4</span></a></td>"
    "<td><span onclick=\"copy('+5511999999999')\">+5511999999999</span></td>"
    "<td><span onclick=\"copy('31/12/2026 \\u002D 23:59')\">31/12/2026 - 23:59</span></td>"
    "<td>Mensal</td><td><span class=\"cliente-valor-cell\">R$ 30,00</span></td>"
    '<td><span class="badge text-bg-success">Ativo</span></td>'
    "<td><a href='https://painel.example/#/login'>UNITV</a></td>"
    "<td>1</td><td>UNITV</td><td>TV Box</td><td>Venda direta</td><td>-</td><td></td>"
    "<td>Enviar Agora</td></tr>"
)


def test_parse_row_extrai_tudo():
    r = rocket._parse_row(ROW)
    assert r["id"] == "1613748"
    assert r["uuid"] == "01a104cf-fa66-788a-b7c3-7c272ada0aa8"
    assert r["nome"] == "Zz_Test_Probe"
    assert r["login"] == "zztestp4"
    assert r["telefone"] == "+5511999999999"
    assert r["vencimento"] == "31/12/2026 - 23:59"  # \u002D vira hífen
    assert r["plano"] == "Mensal"
    assert r["valor"] == "R$ 30,00"
    assert r["status"] == "Ativo"
    assert r["servidor"] == "UNITV"


def test_urls_de_post():
    c = rocket.RocketGestorClient.__new__(rocket.RocketGestorClient)
    assert rocket._ADD == "/gerenciador/cliente/add"
    assert rocket._MASS_DELETE or True  # constante existe
    # update: rota correta é editar?cliente_id=
    import re as _re
    src = _re.sub(r"\s+", " ", open(rocket.__file__, encoding="utf-8").read())
    assert "/gerenciador/cliente/editar?cliente_id=" in src
    assert "/gerenciador/cliente/delete?cliente_id=" in src


def test_create_payload_form_encoded():
    """create monta dict (não json) — o form Django espera form-encoded."""
    class FakeResp:
        status_code = 200
        text = "<html></html>"

    captured = {}

    class FakeClient(rocket.RocketGestorClient):
        def _csrf_from(self, path):
            return "TOKEN"

        def _post(self, path, data):
            captured["path"] = path
            captured["data"] = data
            return FakeResp()

    c = FakeClient.__new__(FakeClient)
    res = c.create_client({"nome": "zz", "usuario": "zz_test_x",
                           "plano": "13638", "forma_de_pagamento": "4017"})
    assert captured["path"] == rocket._ADD
    assert captured["data"]["teste_id"] == ""
    assert captured["data"]["csrfmiddlewaretoken"] == "TOKEN"
    assert captured["data"]["plano"] == "13638"
    assert res["ok"] is True


def test_delete_verifica_lixeira_no_500():
    """delete 500 → confere na lixeira antes de dizer ok (comportamento real)."""
    class FakeResp:
        status_code = 200

        def __init__(self, text):
            self.text = text

    class FakeClient(rocket.RocketGestorClient):
        def list_clients(self, status=None, max_pages=50):
            return [{"id": "1", "uuid": "abc", "login": "zz_test_x", "nome": "Zz"}]

        def _get(self, path):
            if "delete?cliente_id=abc" in path:
                raise rocket.RocketGestorError("GET ... -> 500")
            if "/clientes/lixeira/" in path:
                return "<html>sem o cliente aqui</html>"  # lixeira SEM o login
            return "<html>info</html>"  # info page

    c = FakeClient.__new__(FakeClient)
    res = c.delete_client("1")
    assert res["ok"] is False  # login não está na lixeira = não deletado


def test_delete_500_mas_deletado():
    class FakeResp:
        status_code = 200

        def __init__(self, text):
            self.text = text

    class FakeClient(rocket.RocketGestorClient):
        def list_clients(self, status=None, max_pages=50):
            return [{"id": "1", "uuid": "abc", "login": "zz_test_x", "nome": "Zz"}]

        def _get(self, path):
            if "delete?cliente_id=abc" in path:
                raise rocket.RocketGestorError("GET ... -> 500")
            if "/clientes/lixeira/" in path:
                return "<html>Zz zz_test_x</html>"  # lixeira COM o login
            return "<html>info</html>"

    c = FakeClient.__new__(FakeClient)
    res = c.delete_client("1")
    assert res["ok"] is True


def test_alert_honesto():
    html = '<div class="alert alert-danger"><i class="bi"></i> usuario: Já existe</div>'
    r = type("R", (), {"text": html})()
    assert rocket.RocketGestorClient._alert(None, r) == "usuario: Já existe"


def test_parse_json_inexistente_nao_quebra_import():
    json.loads("{}")  # sanidade
    assert callable(rocket._txt)
