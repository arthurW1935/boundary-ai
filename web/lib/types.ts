export type Conversation = {
  id: string;
  title: string;
  token_budget: number | null;
  cost_budget: number | null;
  spent_tokens: number;
  spent_cost: number;
  created_at: string;
};

export type Message = {
  id: string;
  role: string;
  content: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

export type ChatResponse = {
  conversation_id: string;
  run_id: string;
  status: string;
  assistant_message: string;
  tool_call?: {
    server_id: string;
    tool_name: string;
    arguments: Record<string, unknown>;
  } | null;
  approval_request_id?: string | null;
};

export type Policy = {
  id: string;
  name: string;
  rule_type: string;
  enabled: boolean;
  priority: number;
  target_tool: string | null;
  target_server_id: string | null;
  conditions: Record<string, unknown> | null;
  action: Record<string, unknown> | null;
  created_at: string;
};

export type Approval = {
  id: string;
  run_id: string;
  conversation_id: string;
  server_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
  reason: string;
  expires_at: string;
  comment: string | null;
  created_at: string;
};

export type AuditEvent = {
  id: string;
  conversation_id: string | null;
  run_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type MCPServer = {
  id: string;
  name: string;
  transport: string;
  enabled: boolean;
  config: Record<string, unknown>;
  last_error: string | null;
  last_discovered_at: string | null;
  tool_count: number;
};

export type MCPTool = {
  server_id: string;
  server_name: string;
  transport: string;
  name: string;
  description: string | null;
  input_schema: Record<string, unknown> | null;
};
