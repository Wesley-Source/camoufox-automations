from core.sigma.auth import load_session


def test_load_session(tmp_path):
    # arquivo inexistente
    assert load_session(str(tmp_path / "nope.json")) is None
    # json corrompido
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_session(str(bad)) is None
    # incompleto (falta token)
    partial = tmp_path / "partial.json"
    partial.write_text('{"cookies": [1]}', encoding="utf-8")
    assert load_session(str(partial)) is None
    # Bearer-only (cookies vazios é válido — ex.: newmais)
    nocookie = tmp_path / "nocookie.json"
    nocookie.write_text('{"token": "t", "cookies": []}', encoding="utf-8")
    assert load_session(str(nocookie)) == {"token": "t", "cookies": []}
    # válida
    good = tmp_path / "good.json"
    good.write_text('{"token": "t", "cookies": [1]}', encoding="utf-8")
    assert load_session(str(good)) == {"token": "t", "cookies": [1]}


# ---- Onda B: A2 redação genérica de senha no monitor ------------------------

class _FakeReq:
    def __init__(self, post_data):
        self.post_data = post_data
        self.method = "POST"


class _FakeResp:
    def __init__(self, url, post_data):
        self.url = url
        self.status = 201
        self.request = _FakeReq(post_data)

    def text(self):
        return "{}"


class _FakePage:
    def __init__(self):
        self.handler = None

    def on(self, event, handler):
        self.handler = handler


def test_monitor_redige_senha_generica():
    from core.sigma.auth import _attach_api_monitor
    page = _FakePage()
    captured = []
    _attach_api_monitor(page, captured)
    page.handler(_FakeResp("https://lideriptv.sigma.st/api/customers",
                           '{"password":"Secret1"}'))
    page.handler(_FakeResp("https://lideriptv.sigma.st/api/customers",
                           '{"note":"sem senha"}'))
    assert captured[0]["post_data"] == "[REDACTED]"      # A2: senha genérica
    assert captured[1]["post_data"] != "[REDACTED]"      # corpo inofensivo passa


def test_validacao_erro_de_rede_propaga(monkeypatch):  # M7
    import pytest
    from core.sigma import auth
    monkeypatch.setattr(auth, "_VALIDATE_SETTLE", 0)

    class BoomPage:
        def goto(self, *a, **kw):
            raise RuntimeError("net down")

    with pytest.raises(RuntimeError, match="rede/proxy"):
        auth._session_still_valid(BoomPage(), [], "tok")
