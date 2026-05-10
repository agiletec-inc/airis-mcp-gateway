# AIRIS Playbook

Use AIRIS as the shared capability layer and keep project repositories free of local `mcp.json`.

Core rules:
- Check docs before implementation. For library or API work, prefer `context7`.
- Use MCP for shared external APIs and structured I/O.
- Use CLI for deterministic local workflows such as `git`, `gh`, `docker`, `pytest`, and Playwright.
- Prefer Playwright CLI over Playwright MCP for normal testing because it is faster and more token-efficient.
- Use skills, hooks, and command packs for workflow guidance, guardrails, and repeatable operating procedures.
- For larger changes, work in the order: inspect, design, implement, verify.

Capability routing:
- Docs lookup: `context7`
- Current web information: `tavily`
- Payments: `stripe`
- Database and storage: `supabase`
- Browser testing: Playwright CLI
- Simple code edits and file reads: native editor and shell tools

The goal is not only tool access. The goal is reliable tool choice with less rework.
