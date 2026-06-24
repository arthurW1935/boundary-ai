"use client";

import { FormEvent, useEffect, useState } from "react";

import { apiGet, apiSend } from "@/lib/api";
import { Policy } from "@/lib/types";
import { useLiveRefresh } from "@/lib/use-live-refresh";

const DEFAULT_FORM = {
  name: "",
  ruleType: "block_tool",
  targetTool: "",
  priority: 100,
  conditions: "{}",
  action: "{\"reason\":\"Explain why this rule exists\"}"
};

const PRESETS = {
  blockDelete: {
    name: "Block deletes",
    ruleType: "block_tool",
    targetTool: "delete_file",
    priority: 200,
    conditions: "{}",
    action: "{\"reason\":\"Deletes are blocked in this demo\"}"
  },
  approveWrite: {
    name: "Approve writes",
    ruleType: "require_approval",
    targetTool: "write_file",
    priority: 150,
    conditions: "{}",
    action: "{\"reason\":\"Writes require human approval\"}"
  },
  restrictNotes: {
    name: "Notes only",
    ruleType: "validate_args",
    targetTool: "write_file",
    priority: 180,
    conditions: "{\"path_arg\":\"path\",\"allow_prefixes\":[\"notes/\"]}",
    action: "{}"
  }
};

export default function PoliciesPage() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [form, setForm] = useState(DEFAULT_FORM);

  async function loadPolicies() {
    const data = await apiGet<Policy[]>("/api/policies");
    setPolicies(data);
  }

  useEffect(() => {
    loadPolicies().catch((error) => setStatus(String(error)));
  }, []);

  useLiveRefresh(() => {
    loadPolicies().catch(() => undefined);
  });

  async function createPolicy(event: FormEvent) {
    event.preventDefault();
    try {
      if (!form.name.trim()) {
        setStatus("Policy name is required.");
        return;
      }

      const conditions = JSON.parse(form.conditions);
      const action = JSON.parse(form.action);
      await apiSend("/api/policies", {
        method: "POST",
        body: JSON.stringify({
          name: form.name.trim(),
          rule_type: form.ruleType,
          target_tool: form.targetTool || null,
          priority: Number(form.priority),
          conditions,
          action
        })
      });
      setForm(DEFAULT_FORM);
      setStatus("Policy created.");
      await loadPolicies();
    } catch (error) {
      setStatus(`Policy JSON is invalid or request failed: ${String(error)}`);
    }
  }

  async function togglePolicy(policy: Policy) {
    try {
      await apiSend(`/api/policies/${policy.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !policy.enabled })
      });
      await loadPolicies();
    } catch (error) {
      setStatus(String(error));
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h2>Policies</h2>
          <p>
            Create deterministic guardrails that apply before any MCP tool runs. These rules are
            the real control point, not the model prompt.
          </p>
        </div>
        <span className="badge">{status ?? "Live policy plane"}</span>
      </header>

      <div className="grid two">
        <section className="panel">
          <h3>Create Rule</h3>
          <div className="row wrap" style={{ marginBottom: 14 }}>
            <button className="button secondary" onClick={() => setForm(PRESETS.blockDelete)}>
              Block deletes
            </button>
            <button className="button secondary" onClick={() => setForm(PRESETS.approveWrite)}>
              Approval for writes
            </button>
            <button className="button secondary" onClick={() => setForm(PRESETS.restrictNotes)}>
              Notes path only
            </button>
          </div>
          <form className="stack" onSubmit={createPolicy}>
            <div className="field">
              <label>Name</label>
              <input
                required
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                placeholder="Block deletes"
              />
            </div>
            <div className="field">
              <label>Rule type</label>
              <select
                value={form.ruleType}
                onChange={(event) => setForm((current) => ({ ...current, ruleType: event.target.value }))}
              >
                <option value="block_tool">block_tool</option>
                <option value="require_approval">require_approval</option>
                <option value="validate_args">validate_args</option>
                <option value="token_budget">token_budget</option>
                <option value="cost_budget">cost_budget</option>
              </select>
            </div>
            <div className="field">
              <label>Target tool</label>
              <input
                value={form.targetTool}
                onChange={(event) =>
                  setForm((current) => ({ ...current, targetTool: event.target.value }))
                }
                placeholder="delete_file"
              />
            </div>
            <div className="field">
              <label>Priority</label>
              <input
                type="number"
                value={form.priority}
                onChange={(event) =>
                  setForm((current) => ({ ...current, priority: Number(event.target.value) }))
                }
              />
            </div>
            <div className="field">
              <label>Conditions JSON</label>
              <textarea
                value={form.conditions}
                onChange={(event) =>
                  setForm((current) => ({ ...current, conditions: event.target.value }))
                }
              />
            </div>
            <div className="field">
              <label>Action JSON</label>
              <textarea
                value={form.action}
                onChange={(event) =>
                  setForm((current) => ({ ...current, action: event.target.value }))
                }
              />
            </div>
            <button className="button">Create Policy</button>
          </form>
        </section>

        <section className="panel stack">
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <h3>Active Rules</h3>
            <button className="button secondary" onClick={() => loadPolicies()}>
              Refresh
            </button>
          </div>
          <div className="list">
            {policies.map((policy) => (
              <div className="card" key={policy.id}>
                <div className="row wrap" style={{ justifyContent: "space-between" }}>
                  <strong>{policy.name}</strong>
                  <span className={`badge ${policy.enabled ? "success" : "danger"}`}>
                    {policy.enabled ? "enabled" : "disabled"}
                  </span>
                </div>
                <p className="muted">
                  {policy.rule_type} / target `{policy.target_tool ?? "*"}` / priority{" "}
                  {policy.priority}
                </p>
                <pre>{JSON.stringify({ conditions: policy.conditions, action: policy.action }, null, 2)}</pre>
                <div className="row wrap" style={{ marginTop: 12 }}>
                  <button className="button secondary" onClick={() => togglePolicy(policy)}>
                    {policy.enabled ? "Disable" : "Enable"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
