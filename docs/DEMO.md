# Demo Notes

## Local Startup
- Backend venv:
  - `python -m venv api/.venv`
  - `api/.venv\Scripts\pip install -e mcp_server -e api pytest`
- Frontend:
  - `cd web`
  - `npm install`
- Run services:
  - API: `api/.venv\Scripts\uvicorn armoriq_api.main:app --reload --app-dir api/src`
  - Web: `cd web && npm run dev`

## Recommended Demo Flow
1. Open `MCP Servers` and show the seeded `local-sandbox` server.
2. Open `Policies` and create:
   - `block_tool` for `delete_file`
   - `require_approval` for `write_file`
3. Open `Chat` and send:
   - `list files`
   - `write file notes/demo.txt: hello from the guarded agent`
4. Show the write pausing for approval.
5. Open `Approvals` and approve the pending tool call.
6. Return to `Chat` and show the assistant response after resume.
7. Send:
   - `delete file notes/demo.txt`
8. Show the tool call getting blocked.
9. Open `Audit Logs` and walk through:
   - tool discovery
   - policy decision
   - approval request
   - approval decision
   - tool result

## Sample Policy Payloads
- Block deletes:
```json
{
  "name": "Block deletes",
  "rule_type": "block_tool",
  "target_tool": "delete_file",
  "priority": 200,
  "conditions": {},
  "action": {
    "reason": "File deletion is disabled in this demo."
  }
}
```

- Require approval for writes:
```json
{
  "name": "Approve writes",
  "rule_type": "require_approval",
  "target_tool": "write_file",
  "priority": 150,
  "conditions": {},
  "action": {
    "reason": "Writes require explicit human review."
  }
}
```

- Restrict writable paths:
```json
{
  "name": "Sandbox notes only",
  "rule_type": "validate_args",
  "target_tool": "write_file",
  "priority": 180,
  "conditions": {
    "path_arg": "path",
    "allow_prefixes": ["notes/"]
  },
  "action": {}
}
```

## Remote MCP Notes
- The backend supports `sse` and `streamable_http` MCP transports.
- To add an external MCP server:
  - open `MCP Servers`
  - choose the transport
  - paste the transport config JSON
- The repo does not ship a live `Context7` endpoint because remote MCP URLs and auth can differ by environment. Configure it through the UI or `REMOTE_MCP_*` env vars when you have the real endpoint details.
