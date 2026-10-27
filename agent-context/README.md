# agent-context – contesto per gli agenti di sviluppo

| File | Per chi | Cosa contiene |
|---|---|---|
| `AGENTS.md` | Tutti i tool (Codex, Cursor, …) e il team | Contesto completo: progetto, vincoli di gara, documenti, architettura, struttura, stack e comandi, convenzioni, regole di dominio, Definition of Done, Git, cosa non fare |
| `CLAUDE.md` | Claude Code | Importa `AGENTS.md` + istruzioni specifiche |
| `claude/settings.json` | Claude Code | Permessi di progetto (consentiti lint/test/synth; conferma per deploy, `aws`, push, `rm`; vietati force push e lettura di `.env` e `seed/private/`) |
| `claude/commands/` | Claude Code e Copilot | Comandi slash `/sa-next-task [T-xx] [loop]`, `/sa-dod-check`, `/sa-cds-check` (fonte unica; per Copilot li richiamano i file in `.github/prompts/`) |
| `claude/agents/` | Claude Code | Subagent: `code-reviewer`, `aws-docs-researcher`, `test-runner`, `security-reviewer` |
| `claude/hooks/lint-changed.sh` | Claude Code | Hook `PostToolUse`: lint/format del file appena modificato (ruff, eslint, prettier) |
| `claude/mcp.json` | Claude Code | Server MCP di progetto (AWS Documentation, Amazon Bedrock AgentCore) |
| `github/pull_request_template.md` | GitHub | Template delle PR con la Definition of Done |
| `kiro-steering/product.md` · `tech.md` · `structure.md` | Kiro | Steering file sempre inclusi (`inclusion: always`) |
| `install.sh` | – | Crea link e copie nella root del repo così che i tool trovino i file dove li cercano |

## Attivazione

I tool cercano questi file in posizioni precise (`CLAUDE.md` e `AGENTS.md` nella root, `.claude/settings.json`, `.claude/commands/`, `.claude/agents/`, `.mcp.json`, `.kiro/steering/`, `.github/`). Setup del team: `START_HERE.md` §1.1. Dalla root di `SuppliAgent/`:

```bash
bash agent-context/install.sh
git add -A && git commit -m "chore: activate agent context"
```

Lo script crea link simbolici (e copie per `.mcp.json` e il template PR): i file si modificano **solo qui** in `agent-context/`.
Tutti i percorsi citati nei file sono relativi alla root del repository.
