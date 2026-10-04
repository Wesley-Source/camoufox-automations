# PANEL_MAP — Rocket Gestor (5º site)

- **URL**: `https://app.rocketgestor.com` · **mapeado em 03/10/2026**
- **Stack**: Django **server-rendered** (NÃO é família Sigma — nada de localStorage/Bearer/DoH).
  Cloudflare na frente, porém permissivo: GETs passam sem challenge.
- **Sessão**: COOKIES (`sessionid`/`csrftoken`) via `rocketgestor_session.json`;
  login form `#login-form` (`csrfmiddlewaretoken` + `username`/`password`) em
  `/accounts/login/`. `load_session` válido = cookies não-vazios.
- **Conta**: `tcitvstreaming` (creds em `rocketgestor_accounts.json` 0600).
- **⚠️ Política de créditos — EXCEÇÃO no hub**: Rocket Gestor NÃO tem sistema de
  créditos. **Liberado criar/alterar/deletar CLIENTES DE TESTE (`zz_test_*`) à
  vontade** para validar CRUD — **clientes REAIS seguem intocados** (regra 2 do
  AGENTS.md continua valendo para entidades reais).
- **Auth própria** (`core/rocketgestor/auth.py`): standalone, fora das bases
  sigma (sessão por cookies, não Bearer). Guard central `core/guard.py` usado
  igual nos irmãos.

## Rotas mapeadas (46 — `out/crawled.json`)

- **Clientes**: `/gerenciador/clientes/` (+ filtros `?status=Ativo|Vencido|Vence Hoje`,
  `?dif_dias_vencimento=N`) — 1 tabela por página; **criar = `POST /gerenciador/cliente/add`**
- **Revenda**: `/gerenciador/revendedores/`, `/gerenciador/revendas/dashboard`,
  `/gerenciador/revendedor/compracreditos`, `POST /gerenciador/revendedor/add`,
  `/revendedor/renovar-sistema/`
- **Catálogo**: `/gerenciador/planos`, `/gerenciador/lista_servidores/`,
  `/gerenciador/lista_aplicativos/`, `/gerenciador/lista_dispositivos/`,
  `/gerenciador/tags-personalizadas/`
- **Financeiro**: `/gerenciador/pagamentos/`, `/gerenciador/cobrancas/`,
  `/gerenciador/transacoes/clientes/`, `/gerenciador/formas_de_pagamento/`,
  `/gerenciador/portal/chaves-pix/`
- **Mensageria**: `/whatsapp/sessoes/`, `/gerenciador/mensagens/`,
  `/gerenciador/mensagens_agendadas/`, `/gerenciador/enviosAutomaticosTestes/`
- **API externa do produto**: `/gerenciador/api-keys/`, `/gerenciador/api-logs/`
  (o Rocket OFERECE API externa — caminho promissor para a Fase 2 em vez de
  raspar HTML)
- **Operação**: `/gerenciador/dashboard/`, `/gerenciador/auditoria/`,
  `/gerenciador/testes/`, `/gerenciador/integracoes/`, `/gerenciador/importar-clientes/`,
  `/gerenciador/exportador/`, `/gerenciador/exportarContatos/`,
  `/gerenciador/portal/{configuracoes,contatos,mapeamento,alertas}/`,
  `/gerenciador/motivoNaoConvertido/`, `/editar_perfil/`, `/tutoriais/`,
  `/pay/integracoes/`

## Probe de API (04)

Nenhum endpoint REST nos caminhos chutados (`/api/clients/` etc. → 404);
`/api/` responde 200 em HTML. A API real do produto provavelmente exige
API key (página `/gerenciador/api-keys/`) — verificar na Fase 2.

## Fase 2 (aguardando aprovação do mapa)

Snapshot da tabela de clientes (URLs de detalhe/edição por id), API externa
via api-keys (preferir a HTML), port api/scraper/CLI/MCP no padrão do hub
(kinds `rocketgestor.*`), CRUD test-friendly (zz_test_* livres).
