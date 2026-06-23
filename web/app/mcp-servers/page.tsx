"use client";

import { FormEvent, useEffect, useState } from "react";

import { apiGet, apiSend } from "@/lib/api";
import { MCPServer, MCPTool } from "@/lib/types";
import { useLiveRefresh } from "@/lib/use-live-refresh";

const DEFAULT_CONFIG = "{\n  \"url\": \"https://example.com/mcp\"\n}";

export default function MCPServersPage() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [transport, setTransport] = useState("sse");
  const [config, setConfig] = useState(DEFAULT_CONFIG);

  async function loadAll() {
    const [serverData, toolData] = await Promise.all([
      apiGet<MCPServer[]>("/api/mcp/servers"),
      apiGet<MCPTool[]>("/api/mcp/tools")
    ]);
    setServers(serverData);
    setTools(toolData);
  }

  useEffect(() => {
    loadAll().catch((error) => setStatus(String(error)));
  }, []);

  useLiveRefresh(() => {
    loadAll().catch(() => undefined);
  });

  async function createServer(event: FormEvent) {
    event.preventDefault();
    try {
      await apiSend("/api/mcp/servers", {
        method: "POST",
        body: JSON.stringify({
          name,
          transport,
          enabled: true,
          config: JSON.parse(config)
        })
      });
      setName("");
      setTransport("sse");
      setConfig(DEFAULT_CONFIG);
      setStatus("Server registered.");
      await loadAll();
    } catch (error) {
      setStatus(String(error));
    }
  }

  async function refreshServer(serverId: string) {
    try {
      await apiSend(`/api/mcp/servers/${serverId}/refresh`, { method: "POST", body: "{}" });
      await loadAll();
      setStatus("Server refreshed.");
    } catch (error) {
      setStatus(String(error));
    }
  }

  async function toggleServer(server: MCPServer) {
    try {
      await apiSend(`/api/mcp/servers/${server.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !server.enabled })
      });
      await loadAll();
    } catch (error) {
      setStatus(String(error));
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h2>MCP Servers</h2>
          <p>
            Register local or remote MCP endpoints here. Tool discovery is live and the agent uses
            whatever each active server exposes.
          </p>
        </div>
        <span className="badge">{status ?? `${tools.length} discovered tools`}</span>
      </header>

      <div className="grid two">
        <section className="panel">
          <h3>Add MCP Server</h3>
          <form className="stack" onSubmit={createServer}>
            <div className="field">
              <label>Name</label>
              <input value={name} onChange={(event) => setName(event.target.value)} />
            </div>
            <div className="field">
              <label>Transport</label>
              <select value={transport} onChange={(event) => setTransport(event.target.value)}>
                <option value="sse">sse</option>
                <option value="streamable_http">streamable_http</option>
                <option value="stdio">stdio</option>
              </select>
            </div>
            <div className="field">
              <label>Config JSON</label>
              <textarea value={config} onChange={(event) => setConfig(event.target.value)} />
            </div>
            <button className="button">Register</button>
          </form>
        </section>

        <section className="panel stack">
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <h3>Connected Servers</h3>
            <button className="button secondary" onClick={() => loadAll()}>
              Refresh
            </button>
          </div>
          <div className="list">
            {servers.map((server) => (
              <div className="card" key={server.id}>
                <div className="row wrap" style={{ justifyContent: "space-between" }}>
                  <strong>{server.name}</strong>
                  <span className={`badge ${server.enabled ? "success" : "danger"}`}>
                    {server.enabled ? "enabled" : "disabled"}
                  </span>
                </div>
                <p className="muted">
                  {server.transport} · {server.tool_count} tools
                </p>
                {server.last_error && <p style={{ color: "var(--danger)" }}>{server.last_error}</p>}
                <pre>{JSON.stringify(server.config, null, 2)}</pre>
                <div className="row wrap" style={{ marginTop: 12 }}>
                  <button className="button secondary" onClick={() => refreshServer(server.id)}>
                    Refresh Tools
                  </button>
                  <button className="button secondary" onClick={() => toggleServer(server)}>
                    {server.enabled ? "Disable" : "Enable"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="panel" style={{ marginTop: 18 }}>
        <h3>Discovered Tool Catalog</h3>
        <div className="list">
          {tools.map((tool) => (
            <div className="card" key={`${tool.server_id}-${tool.name}`}>
              <div className="row wrap" style={{ justifyContent: "space-between" }}>
                <strong>{tool.name}</strong>
                <span className="badge">{tool.server_name}</span>
              </div>
              <p className="muted">{tool.description ?? "No description provided."}</p>
              <pre>{JSON.stringify(tool.input_schema, null, 2)}</pre>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
