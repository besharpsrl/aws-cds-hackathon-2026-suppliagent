#!/usr/bin/env bash
# Attiva il contesto per gli agenti di sviluppo creando link (e copie) nella root del repo.
# Uso (dalla root di SuppliAgent/):  bash agent-context/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Contesto condiviso
ln -sfn agent-context/AGENTS.md AGENTS.md                         # Codex, Cursor, altri tool
ln -sfn agent-context/CLAUDE.md CLAUDE.md                         # Claude Code (importa @AGENTS.md)
mkdir -p .kiro
ln -sfn ../agent-context/kiro-steering .kiro/steering             # Kiro steering

# Claude Code: permessi di progetto, comandi slash, server MCP
mkdir -p .claude
ln -sfn ../agent-context/claude/settings.json .claude/settings.json
ln -sfn ../agent-context/claude/commands .claude/commands
ln -sfn ../agent-context/claude/agents .claude/agents             # subagent di progetto
chmod +x agent-context/claude/hooks/*.sh 2>/dev/null || true
cp agent-context/claude/mcp.json .mcp.json                        # copia: alcuni client non seguono i link

# GitHub: template PR (copia, GitHub non segue i link simbolici)
mkdir -p .github
cp agent-context/github/pull_request_template.md .github/pull_request_template.md

echo "Contesto agenti attivato: AGENTS.md, CLAUDE.md, .kiro/steering, .claude/{settings.json,commands,agents}, .mcp.json, .github/pull_request_template.md"
echo "Ricorda: se modifichi agent-context/claude/mcp.json o agent-context/github/, rilancia questo script."
