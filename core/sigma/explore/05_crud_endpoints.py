"""
Etapa 5 da exploração do painel Sigma — mapa dos endpoints de ESCRITA.

100% READ-ONLY: baixa os chunks JS do SPA (via fetch dentro da página,
mesmo transporte que funciona contra Cloudflare) e extrai por regex todos
os paths de API que citam customers/renew/suspend/etc., inferindo o verbo
HTTP pelo método axios no contexto do código minificado.

Nenhuma requisição mutante é feita aqui. A saída alimenta o 06, que é
quem executa o ciclo de vida — e somente do cliente teste.

Saída: out/crud_endpoints.json

Rode: venv/bin/python core/sigma/explore/05_crud_endpoints.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.sigma.auth import ensure_logged_page  # noqa: E402
from core.sigma.explore._guard import install_guard, report_blocked  # noqa: E402

OUT = Path(__file__).parent / "out"
MAX_FILES = 120  # ponytail: BFS nos imports com teto — SPA carrega ~76 chunks
# Rotas cuja visita força o lazy-load dos chunks com o CRUD de clientes
# (navegação = GET; nada é preenchido nem enviado).
KEY_ROUTES = [
    "/customers/add",
    "/customers/edit/ze15VO34L5",  # id real já exposto no mapa — só renderiza o form
    "/customers/renewal-assistant",
    "/customers/migration",
]

# Paths de API que interessam para o ciclo de vida do cliente.
INTEREST = re.compile(r"customer|renew|suspend|expire|note|migration|botbot", re.I)
# Verbo axios no código minificado (nomes de método sobrevivem ao minify).
VERBS = re.compile(r"\.(get|post|put|patch|delete)\(\s*([`\"'])([^`\"']+)\2")
# Estilo config-object: e({url:"customers/x",method:"post",...}) (e variantes).
CFG = re.compile(
    r"""\{[^{}]{0,200}?url:\s*([`"'])([^`"']+)\1[^{}]{0,200}?method:\s*["'](\w+)["']"""
)
CFG_REV = re.compile(
    r"""\{[^{}]{0,200}?method:\s*["'](\w+)["'][^{}]{0,200}?url:\s*([`"'])([^`"']+)\2"""
)
FETCH_CHUNK = (
    "async (u) => { const r = await fetch(u); "
    "return r.ok ? await r.text() : null; }"
)


def js_imports(text: str) -> list[str]:
    """Imports relativos minificados: from"./Chunk-hash.js" e import("./x.js")."""
    return [
        m
        for m in re.findall(r"""["'](\.\.?/[^"']+\.js)["']""", text)
    ]


def asset_url(src: str, base: str) -> str:
    if src.startswith("http"):
        return src
    root = base.rsplit("/", 1)[0]
    return f"{root}/{src.lstrip('./')}" if not src.startswith("/") else f"https://{base.split('/')[2]}{src}"


def main():
    typer.echo("Abrindo painel (sessão salva)...")
    with ensure_logged_page(guard=install_guard) as s:
        page = s.page
        entry = page.evaluate(
            "() => [...document.querySelectorAll('script[src]')].map(x => x.src)"
        )
        # Visita as rotas-chave p/ forçar o lazy-load dos chunks de CRUD
        # (navegação hash = GET; guard ativo bloquearia qualquer POST).
        import time

        for route in KEY_ROUTES:
            try:
                page.evaluate(f"() => location.hash = '{route}'")
                time.sleep(4)
            except Exception as e:
                typer.echo(f"  (skip rota) {route}: {str(e).splitlines()[0][:60]}")
        loaded = page.evaluate(
            """() => performance.getEntriesByType("resource")
                   .map(e => e.name).filter(u => u.endsWith(".js"))"""
        )
        if not entry:
            typer.secho("✖ Nenhum <script src> no DOM — SPA não carregou?", fg=typer.colors.RED)
            raise typer.Exit(1)

        queue, seen, texts = list(dict.fromkeys(entry + loaded)), set(), {}
        while queue and len(seen) < MAX_FILES:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            try:
                body = page.evaluate(FETCH_CHUNK, url)
            except Exception as e:  # CDN externa/CORS/network — chunk inacessível, segue o baile
                typer.echo(f"  (skip) {url.rsplit('/', 1)[-1]}: {str(e).splitlines()[0][:60]}")
                continue
            if not body:
                continue
            texts[url] = body
            for rel in js_imports(body):
                nxt = asset_url(rel, url)
                if nxt not in seen:
                    queue.append(nxt)
        typer.echo(f"Baixados {len(texts)} chunks JS (limite {MAX_FILES}).")

    findings = []
    for url, text in texts.items():
        for m in VERBS.finditer(text):
            verb, _, raw_path = m.groups()
            if not INTEREST.search(raw_path):
                continue
            snippet = text[max(0, m.start() - 80): m.end() + 80].replace("\n", " ")
            findings.append(
                {
                    "verb": verb.upper(),
                    "path": raw_path,
                    "chunk": url.rsplit("/", 1)[-1],
                    "snippet": snippet[:200],
                }
            )
        # Estilo config-object: {url:"x",method:"post"} e {method:"post",url:"x"}
        for m in CFG.finditer(text):
            _, raw_path, verb = m.groups()
            if not INTEREST.search(raw_path):
                continue
            snippet = text[max(0, m.start() - 60): m.end() + 60].replace("\n", " ")
            findings.append({"verb": verb.upper(), "path": raw_path,
                             "chunk": url.rsplit("/", 1)[-1], "snippet": snippet[:200]})
        for m in CFG_REV.finditer(text):
            verb, _, raw_path = m.groups()
            if not INTEREST.search(raw_path):
                continue
            snippet = text[max(0, m.start() - 60): m.end() + 60].replace("\n", " ")
            findings.append({"verb": verb.upper(), "path": raw_path,
                             "chunk": url.rsplit("/", 1)[-1], "snippet": snippet[:200]})

    # Dedup por (verb, path com {placeholders} normalizados).
    dedup = {}
    for f in findings:
        key = (f["verb"], re.sub(r"\$\{[^}]+\}", "{id}", f["path"]))
        dedup.setdefault(key, f)

    OUT.mkdir(exist_ok=True)
    data = {
        "chunks_scanned": len(texts),
        "endpoints": sorted(dedup.values(), key=lambda f: (f["path"], f["verb"])),
    }
    (OUT / "crud_endpoints.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    typer.secho(f"\n✔ {len(dedup)} endpoint(s) de escrita/leitura relevantes:", fg=typer.colors.GREEN)
    for f in sorted(dedup.values(), key=lambda f: (f["path"], f["verb"])):
        typer.echo(f"  {f['verb']:7s} {f['path']}")
    report_blocked(s.blocked)
    typer.secho(f"✔ Detalhes em {OUT / 'crud_endpoints.json'}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    main()
