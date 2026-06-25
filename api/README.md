# API

FastAPI control plane for the guarded MCP agent.

## Responsibilities
- host chat and admin APIs
- manage MCP server discovery and execution
- evaluate tool intents through the policy engine
- orchestrate approvals and audit logs
- expire stale approvals in the background
- publish live events through Redis pub/sub when configured

## Run
- `uvicorn armoriq_api.main:app --reload --app-dir api/src`

## Reviewed Defaults
- `LLM_PROVIDER=openai`
- `ALLOW_DEMO_MOCK_PLANNER=false`
- `DATABASE_URL=postgresql+asyncpg://armoriq:armoriq@localhost:5432/armoriq`
- `REDIS_URL=redis://localhost:6379/0`
