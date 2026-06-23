# API

FastAPI control plane for the guarded MCP agent.

## Responsibilities
- host chat and admin APIs
- manage MCP server discovery and execution
- evaluate tool intents through the policy engine
- orchestrate approvals and audit logs

## Run
- `uvicorn armoriq_api.main:app --reload --app-dir api/src`
