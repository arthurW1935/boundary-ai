# Guarded MCP Agent

A full-stack demo of a guarded AI agent that discovers tools from MCP servers at runtime, evaluates every tool intent through a separate policy engine, and lets an admin dashboard control approvals and guardrails live.

## Stack
- `web/`: Next.js dashboard
- `api/`: FastAPI control plane and agent runtime
- `mcp_server/`: custom sandboxed file MCP server

## Docs
- [Architecture](./ARCHITECTURE.MD)
- [Demo Notes](./docs/DEMO.md)

## What Works Now
- Two MCP servers connected by default:
  - local sandbox MCP over `stdio`
  - Exa hosted MCP over `streamable_http`
- Dynamic tool discovery from both servers
- Guardrail evaluation before every tool call
- Human approval workflow for sensitive tools
- Multi-step tool runs in a single chat prompt
- Approval resume is re-checked against the latest policy state
- Pending approvals expire automatically and default deny
- Conversation budgets can stop the run before another tool executes

## Quick Start
1. Copy env files:
   - `api/.env.example` -> `api/.env`
   - `web/.env.example` -> `web/.env.local`
2. Set `OPENAI_API_KEY` in `api/.env`.
   - The reviewed runtime uses the OpenAI-compatible planner by default.
   - `LLM_PROVIDER=mock` is now local-demo only and requires `ALLOW_DEMO_MOCK_PLANNER=true`.
3. Start infra:
   - `docker compose up -d postgres redis`
4. Install backend deps:
   - `python -m venv api/.venv`
   - `.\api\.venv\Scripts\python.exe -m pip install -e .\api -e .\mcp_server`
5. Install frontend deps:
   - `cd web && npm install`
6. Run services:
   - API: `api/.venv\Scripts\uvicorn armoriq_api.main:app --reload --app-dir api/src`
   - Web: `cd web && npm run dev`

SQLite remains supported for local-only fallback by setting `DATABASE_URL=sqlite+aiosqlite:///./armoriq.db`, but the default reviewed path uses Postgres + Redis. The API launches the local sandbox MCP server itself over `stdio`.

## Demo Flow
- Start the app and verify both seeded MCP servers:
  - `local-sandbox`
  - `exa`
- Start a chat and let the agent discover tools from both servers.
- Require approval for `write_file`.
- Ask for a remote web search through Exa.
- Queue a `write_file` call, then add a higher-priority block rule before approving it to show post-approval invalidation.
- Block `delete_file`.
- Watch the decision and tool logs update live.

## Edge-Case Stance
- MCP server crash mid-call: surface a structured tool failure, log it, and avoid blind retries for mutating tools.
- Prompt injection: only structured tool intent and arguments are enforceable; the model cannot bypass blocked actions by wording alone.
- Rule conflicts: precedence remains deterministic as `BLOCK > REQUIRE_APPROVAL > ALLOW`, then specificity, then priority.
- Approver offline: approvals expire on TTL and the run is denied automatically without needing a restart or follow-up request.
