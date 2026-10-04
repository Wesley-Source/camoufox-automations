"""Captura os FORMS de cliente do Rocket Gestor (read-only + guard).

Extrai: campos do modal cliente/add (presente em toda página), e de uma
página cliente/info/{id}/: forms de editar + ação de deletar/lixeira.
NÃO submete nada.
"""
import json
import sys
import time

sys.path.insert(0, "/home/ueli/Documentos/Projetos/camoufox-automations")

from core.guard import install_guard, report_blocked
from core.rocketgestor.auth import ROCKET_URL, ensure_logged_page

FORMS_JS = """
() => [...document.querySelectorAll('form')].map(f => ({
  action: f.getAttribute('action'),
  method: (f.method || 'get').toUpperCase(),
  fields: [...f.querySelectorAll('input,select,textarea')].map(i => ({
    name: i.name, type: i.type, required: i.required, tag: i.tagName.toLowerCase(),
    options: i.tagName === 'SELECT' ? [...i.options].slice(0, 8).map(o => o.value || o.text) : undefined,
  })),
}))
"""

LINKS_JS = """
() => [...document.querySelectorAll('a')].map(a => a.getAttribute('href'))
      .filter(h => h && (h.includes('editar') || h.includes('deletar') || h.includes('excluir')
                         || h.includes('lixeira') || h.includes('arquivar')))
"""


def main():
    with ensure_logged_page(guard=install_guard) as s:
        page = s.page
        out = {}

        # 1) Modal add cliente (existe no DOM de /gerenciador/clientes/)
        page.goto(f"{ROCKET_URL}/gerenciador/clientes/", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(5)
        out["add_form"] = page.evaluate(FORMS_JS)

        # 2) Um cliente info — pega edit/delete da página de detalhe
        info = page.evaluate(LINKS_JS)
        out["clientes_links_exemplos"] = info[:20]
        detail_links = page.evaluate(
            "() => [...document.querySelectorAll('a')].map(a => a.getAttribute('href'))"
            ".filter(h => h && h.includes('/cliente/info/'))"
        )
        if detail_links:
            page.goto(f"{ROCKET_URL}{detail_links[0]}", wait_until="domcontentloaded", timeout=60_000)
            time.sleep(5)
            out["info_url"] = detail_links[0]
            out["info_forms"] = page.evaluate(FORMS_JS)
            out["info_action_links"] = page.evaluate(
                "() => [...document.querySelectorAll('a')].map(a => a.getAttribute('href'))"
                ".filter(h => h && /editar|deletar|excluir|arquivar|renovar/i.test(h))"
            )
            out["info_buttons"] = page.evaluate(
                "() => [...document.querySelectorAll('button')].map(b => (b.innerText||'').trim())"
                ".filter(t => t && t.length < 40)"
            )

        path = "/home/ueli/Documentos/Projetos/camoufox-automations/core/rocketgestor/explore/out/cliente_forms.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"salvo em {path}")
        report_blocked(s.blocked)
        print(f"captured: {len(s.captured)} responses")


if __name__ == "__main__":
    main()
