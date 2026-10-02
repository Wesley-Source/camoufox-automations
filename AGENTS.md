## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Painel safety rules (REGRA PERMANENTE — humanos e agentes de IA)

Este hub opera painéis de clientes REAIS (lideriptv, woodcine, painelblackbr, ...).
Créditos e clientes nesses painéis PODEM SER LIMITADOS/PAGOS. Regras inegociáveis:

1. **Exploração é read-only.** Todo script em `core/*/explore/` roda somente-leitura
   e DEVE instalar o guard: `ensure_logged_page(..., guard=install_guard)` de
   `core/guard.py`. Script de exploração sem guard é bug. O log deve terminar com
   `✔ Guard: nenhuma request mutante tentada`.
2. **Nunca criar/renovar/deletar entidade real** (cliente, revendedor, pacote) sem
   aprovação EXPLÍCITA do dono. Nada de "cliente de teste" por conta própria.
3. **Validação de CRUD só por probes não-mutantes**: 422 (POST com payload
   deliberadamente inválido → o backend valida antes de criar, cria NADA), 404
   (PUT/DELETE em ID inexistente), tripwire (contagem/listagem de clientes antes
   e depois de cada probe — divergiu, parou). Sempre com snapshot antes/depois.
4. **Gates destrutivos em dobro**: mutação destrutiva exige flag de ambiente
   `SIGMA_ALLOW_DESTRUCTIVE=1` (humano seta) E confirmação explícita (`--yes` no
   CLI / `confirmar=True` no MCP). Confirmação preenchida pelo próprio agente
   não vale.
5. **Nunca vazar segredos**: saídas usam `project_*` (jamais password, m3u_url,
   renew_url, token completo).
6. **Login sem brute-force**: tentativa errada em `/login` pode contar para ban
   permanente. Só tenta com credencial confirmada; sessão salva é reutilizada
   (os exploradores já fazem isso via `ensure_logged_page`).
7. **Site novo** = seguir o padrão `core/<site>/` (auth multi-conta com
   `<site>_accounts.json` 0600 gitignored, `explore/` com guard, `PANEL_MAP.md`,
   kinds prefixados `<site>.*` no banco). Explorar primeiro, mapear, SÓ DEPOIS
   portar api/scraper/CLI/MCP — e CRUD por último.
