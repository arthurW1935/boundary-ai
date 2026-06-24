# Guarded MCP Agent

A full-stack demo of a guarded AI agent that discovers tools from MCP servers at runtime, evaluates every tool intent through a separate policy engine, and lets an admin dashboard control approvals and guardrails live.

## Stack
- `web/`: Next.js dashboard
- `api/`: FastAPI control plane and agent runtime
- `mcp_server/`: custom sandboxed file MCP server

## What Works Now
- Two MCP servers connected by default:
  - local sandbox MCP over `stdio`
  - Exa hosted MCP over `streamable_http`
- Dynamic tool discovery from both servers
- Guardrail evaluation before every tool call
- Human approval workflow for sensitive tools
- Multi-step tool runs in a single chat prompt

## Quick Start
1. Copy env files:
   - `api/.env.example` -> `api/.env`
   - `web/.env.example` -> `web/.env.local`
2. Start infra:
   - `docker compose up -d postgres redis`
3. Install backend deps:
   - `python -m venv api/.venv`
   - `.\api\.venv\Scripts\python.exe -m pip install -e .\api -e .\mcp_server`
4. Install frontend deps:
   - `cd web && npm install`
5. Run services:
   - MCP server: `api/.venv\Scripts\python -m armoriq_mcp.server`
   - API: `api/.venv\Scripts\uvicorn armoriq_api.main:app --reload --app-dir api/src`
   - Web: `cd web && npm run dev`

## Demo Flow
- Start the app and verify both seeded MCP servers:
  - `local-sandbox`
  - `exa`
- Start a chat and let the agent discover tools from both servers.
- Block `delete_file`.
- Require approval for `write_file`.
- Ask for a remote web search through Exa.
- Watch the decision and tool logs update live.
