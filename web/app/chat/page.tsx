"use client";

import { FormEvent, useEffect, useState } from "react";

import { apiGet, apiSend } from "@/lib/api";
import { useLiveRefresh } from "@/lib/use-live-refresh";
import { ChatResponse, Conversation, Message } from "@/lib/types";

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadConversations() {
    const data = await apiGet<Conversation[]>("/api/conversations");
    setConversations(data);
    if (!selectedConversationId && data[0]) {
      setSelectedConversationId(data[0].id);
    }
  }

  async function loadMessages(conversationId: string) {
    const data = await apiGet<Message[]>(`/api/conversations/${conversationId}/messages`);
    setMessages(data);
  }

  useEffect(() => {
    loadConversations().catch((error) => setStatus(String(error)));
  }, []);

  useEffect(() => {
    if (selectedConversationId) {
      loadMessages(selectedConversationId).catch((error) => setStatus(String(error)));
    } else {
      setMessages([]);
    }
  }, [selectedConversationId]);

  useLiveRefresh(() => {
    loadConversations().catch(() => undefined);
    if (selectedConversationId) {
      loadMessages(selectedConversationId).catch(() => undefined);
    }
  });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) {
      return;
    }

    setBusy(true);
    setStatus("Running agent...");
    try {
      const response = await apiSend<ChatResponse>("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          conversation_id: selectedConversationId,
          message: draft
        })
      });
      setDraft("");
      setStatus(`${response.status}: ${response.assistant_message}`);
      await loadConversations();
      setSelectedConversationId(response.conversation_id);
      await loadMessages(response.conversation_id);
    } catch (error) {
      setStatus(String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="page-header">
        <div>
          <h2>Agent Chat</h2>
          <p>
            Run prompts through the guarded agent. Tool calls are discovered from MCP servers,
            filtered by policy, and surfaced here with approval-aware statuses.
          </p>
        </div>
        <span className="badge warning">{status ?? "Ready"}</span>
      </header>

      <div className="chat-layout">
        <section className="panel stack">
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <h3>Conversations</h3>
            <button className="button secondary" onClick={() => loadConversations()}>
              Refresh
            </button>
          </div>

          <div className="list">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                className="card"
                style={{
                  textAlign: "left",
                  borderColor:
                    selectedConversationId === conversation.id
                      ? "rgba(245, 158, 11, 0.28)"
                      : undefined
                }}
                onClick={() => setSelectedConversationId(conversation.id)}
              >
                <div className="row wrap" style={{ justifyContent: "space-between" }}>
                  <strong>{conversation.title}</strong>
                  <span className="badge">
                    {conversation.spent_tokens} tokens / ${conversation.spent_cost.toFixed(2)}
                  </span>
                </div>
                <p className="muted mono">{conversation.id}</p>
              </button>
            ))}
          </div>
        </section>

        <section className="panel stack">
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <h3>Transcript</h3>
            <span className="badge">{selectedConversationId ?? "new conversation"}</span>
          </div>

          <div className="messages">
            {messages.length === 0 && (
              <div className="message">
                No messages yet. Try `list files`, `write file notes/demo.txt: hello`, or
                `delete file notes/demo.txt`.
              </div>
            )}

            {messages.map((message) => (
              <div key={message.id} className={`message ${message.role}`}>
                <strong>{message.role}</strong>
                <p>{message.content}</p>
              </div>
            ))}
          </div>

          <form className="stack" onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="chat-input">Prompt</label>
              <textarea
                id="chat-input"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask the agent to use a tool..."
              />
            </div>
            <div className="row wrap">
              <button className="button" disabled={busy}>
                {busy ? "Running..." : "Send"}
              </button>
              <span className="muted">
                Sensitive tools will pause here if approval is required.
              </span>
            </div>
          </form>
        </section>
      </div>
    </>
  );
}
