# Claude Code Integration

This repo includes built-in slash commands for Claude Code users. When you open this project in Claude Code, you get instant access to testing and troubleshooting tools.

## Available Commands

| Command | Description |
|---------|-------------|
| `/test` | End-to-end test of gateway health, tools, and pre-warming |
| `/test persistence` | Full test including data persistence across restart |
| `/status` | Quick status check of containers, API, and servers |
| `/troubleshoot [issue]` | Diagnose issues (startup, timeout, tools, connection) |

## Usage

```bash
# In Claude Code TUI, just type:
/test                    # Run full test suite
/status                  # Quick health check
/troubleshoot timeout    # Debug timeout issues
```

## How It Works

Commands live in `.claude/commands/` and become prompts that Claude executes with appropriate tool permissions. This means:

- **Zero setup** - Commands are available as soon as you open the repo
- **Context-aware** - Commands reference project files and config automatically
- **Safe** - Tool permissions are scoped (only docker, curl, MCP tools)

## Creating Custom Commands

Add a markdown file to `.claude/commands/`:

```markdown
# .claude/commands/my-command.md
---
description: What this command does
allowed-tools: Bash(docker*), mcp__airis-mcp-gateway__*
---

Your prompt here. Use $ARGUMENTS for user input.
```
