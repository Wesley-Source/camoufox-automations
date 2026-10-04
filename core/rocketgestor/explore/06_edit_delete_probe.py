"""Captura o modal de EDIÇÃO e o mecanismo de APAGAR do cliente (read-only).

Clica em 'Editar' (abre modal, não submete) e varre o HTML por rotas de
delete. Nada é mutado.
"""
import json
import re
import sys
import time

sys.path.insert(0, "/home/ueli/Documentos/Projetos/camoufox-automations")

from core.guard import install_guard, report_blocked
from core.rocketgestor.auth import ROCKET_URL, ensure_logged_page

FORMS_JS = """
() => [...document.querySelectorAll('form')].map(f => ({
  action: f.getAttribute('action'),
  method: (f.method || 'get').toUpperCase(),
  visible: !!(f.offsetWidth || f.offsetHeight),
  fields: [...f.querySelectorAll('input,select,textarea')].map(i => i.name).filter(Boolean),
}))
"""


def main():
    with ensure_logged_page(guard=install_guard) as s:
        page = s.page
        out = {}

        page.goto(f"{ROCKET_URL}/gerenciador/clientes/", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(5)
        detail = page.evaluate(
            "() => [...document.querySelectorAll('a')].map(a => a.getAttribute('href'))"
            ".filter(h => h && h.includes('/cliente/info/'))"
        )
        page.goto(f"{ROCKET_URL}{detail[0]}", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(5)
        out["info_url"] = detail[0]

        # HTML bruto: procura rotas de delete/editar no JS inline
        html = page.content()
        out["delete_patterns"] = sorted(set(re.findall(r'["\'](/[^"\']*(?:deletar|excluir|apagar|arquivar)[^"\']*)["\']', html)))[:20]
        out["edit_patterns"] = sorted(set(re.findall(r'["\'](/[^"\']*cliente/editar[^"\']*)["\']', html)))[:10]

        # Clica em 'Editar' (só abre modal — NÃO submete)
        try:
            page.get_by_role("button", name="Editar", exact=True).first.click(timeout=10_000)
            time.sleep(3)
            out["edit_modal_forms"] = page.evaluate(FORMS_JS)
        except Exception as e:
            out["edit_modal_error"] = str(e)[:200]

        # Clica em 'Apagar' NÃO — só captura o onclick/handler dele
        out["apagar_html"] = re.findall(r'<button[^>]*>[^<]*Apagar[^<]*</button>|<button[^>]*apagar[^>]*>', html, re.I)[:5]
        out["apagar_onclick"] = re.findall(r'onclick="([^"]*[Aa]pagar[^"]*)"', html)[:5]

        path = "/home/ueli/Documentos/Projetos/camoufox-automations/core/rocketgestor/explore/out/edit_delete.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"salvo em {path}")
        report_blocked(s.blocked)


if __name__ == "__main__":
    main()
