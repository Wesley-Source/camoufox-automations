from core.sigma.auth import load_session


def test_load_session(tmp_path):
    # arquivo inexistente
    assert load_session(str(tmp_path / "nope.json")) is None
    # json corrompido
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_session(str(bad)) is None
    # incompleto (falta cookies)
    partial = tmp_path / "partial.json"
    partial.write_text('{"token": "x"}', encoding="utf-8")
    assert load_session(str(partial)) is None
    # válida
    good = tmp_path / "good.json"
    good.write_text('{"token": "t", "cookies": [1]}', encoding="utf-8")
    assert load_session(str(good)) == {"token": "t", "cookies": [1]}
