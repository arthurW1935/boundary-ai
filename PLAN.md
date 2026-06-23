# Plan

## Delivery Rules
- Work task-by-task.
- Each task ends with a concrete check.
- If the check passes, commit before starting the next task.
- Keep commits small and reviewable.
- Do not mix unrelated changes in one task.

## Task 1: Repo Bootstrap
- Create repo structure:
  - `web/`
  - `api/`
  - `mcp_server/`
  - `docs/`
- Add root docs, env examples, and local dev instructions.
- Add Docker Compose if it clearly speeds up setup.
- Check:
  - folders exist
  - docs exist
  - local start instructions are documented
- Commit:
  - `chore: bootstrap repo structure and docs`

## Task 2: Custom MCP Server
- Implement a sandboxed file-workspace MCP server.
- Add five tools:
  - `list_files`
  - `read_file`
  - `write_file`
  - `delete_file`
  - `search_files`
- Add schema validation and structured errors.
- Check:
  - tool listing works
  - at least two tools execute successfully through MCP
- Commit:
  - `feat: add custom sandbox MCP server`

## Task 3: MCP Integration in Backend
- Add MCP server registry and config model.
- Connect backend to:
  - the custom MCP server
  - one remote MCP server
- Implement dynamic tool discovery and a normalized tool catalog.
- Check:
  - backend lists discovered tools from connected servers
  - runtime logic does not use hardcoded tool names
- Commit:
  - `feat: add dynamic MCP discovery and registry`

## Task 4: Basic Agent Loop
- Add chat and run APIs.
- Implement a thin LLM tool-use loop.
- Let the model call discovered MCP tools through the backend runtime.
- Keep policy enforcement as pass-through for this slice.
- Check:
  - one prompt triggers a real tool call and returns the tool result
- Commit:
  - `feat: add core agent runtime and tool-use loop`

## Task 5: Policy Engine Core
- Implement a separate policy engine module.
- Add rule types:
  - block tool
  - require approval
  - argument validation
  - token budget
  - cost budget
- Add deterministic precedence.
- Intercept every tool intent before execution.
- Check:
  - unit tests cover allow, block, approval, and validation
  - blocked tool calls never reach MCP execution
- Commit:
  - `feat: add policy engine and tool intent enforcement`

## Task 6: Approval Workflow
- Add pending approval models and APIs.
- Pause a run when a tool requires approval.
- Resume the run on approve.
- Terminate or deny on reject or expiry.
- Check:
  - one tool call pauses
  - admin action resumes or denies correctly
- Commit:
  - `feat: add human approval workflow`

## Task 7: Dashboard MVP
- Build pages for:
  - chat
  - policies
  - approvals
  - logs
  - MCP servers
- Add policy CRUD and enable or disable toggles.
- Add approval actions from the UI.
- Check:
  - policy change from the UI affects the running backend without restart
  - pending approval appears live in the UI
- Commit:
  - `feat: add control-plane dashboard MVP`

## Task 8: Realtime Sync and Audit Logs
- Add Redis-backed realtime updates.
- Stream audit events to the dashboard.
- Show tool attempts, verdicts, approvals, failures, and results.
- Check:
  - policy changes propagate live
  - logs update during a run
- Commit:
  - `feat: add realtime sync and audit event streaming`

## Task 9: Hardening and Edge Cases
- Handle MCP disconnects and tool execution failures cleanly.
- Add approval TTL and default deny.
- Add safe handling for invalid tool arguments and server timeouts.
- Add prompt-injection test cases for policy bypass attempts.
- Check:
  - failure cases return structured states
  - guarded actions remain blocked under adversarial prompts
- Commit:
  - `feat: harden runtime against failures and policy bypass attempts`

## Task 10: Demo Readiness
- Polish UI labels and run states.
- Add seed policies and sample prompts.
- Add a short demo script and final notes.
- Verify the full end-to-end story.
- Check:
  - discover tools
  - run a safe tool
  - block a dangerous tool
  - require approval for a sensitive tool
  - show logs
- Commit:
  - `chore: prepare end-to-end demo`

## Suggested Milestones
- Milestone 1:
  - Tasks 1-3
  - outcome: MCP infrastructure works
- Milestone 2:
  - Tasks 4-6
  - outcome: guarded runtime works
- Milestone 3:
  - Tasks 7-8
  - outcome: live control plane works
- Milestone 4:
  - Tasks 9-10
  - outcome: demo-ready submission

## Notes
- Prefer vertical slices over building all backend first and UI later.
- Do not move to the next task until the current task is checked and committed.
- Keep one branch unless review flow forces otherwise.
