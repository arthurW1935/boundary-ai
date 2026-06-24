"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

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
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  const selectedConversation =
    conversations.find((conversation) => conversation.id === selectedConversationId) ?? null;

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

  async function createConversation() {
    const response = await apiSend<{ id: string }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title: "New conversation" })
    });
    await loadConversations();
    setSelectedConversationId(response.id);
    setMessages([]);
    setDraft("");
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

  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [messages, selectedConversationId]);

  useLiveRefresh(() => {
    loadConversations().catch(() => undefined);
    if (selectedConversationId) {
      loadMessages(selectedConversationId).catch(() => undefined);
    }
  });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim() || busy || selectedConversation?.pending_approval) {
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
            Run the guarded agent through a conversation-first workspace. Each thread keeps its own
            MCP activity, policy state, approvals, and audit trail.
          </p>
        </div>
        <span className="badge warning">{status ?? "Ready"}</span>
      </header>

      <div className="chat-shell">
        <aside className="chat-sidebar panel">
          <div className="chat-sidebar-header">
            <div>
              <h3>Conversations</h3>
              <p className="muted">Keep separate guarded runs by task.</p>
            </div>
            <button className="button" onClick={() => createConversation()}>
              New chat
            </button>
          </div>

          <div className="chat-conversation-list">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                className={`conversation-item${
                  selectedConversationId === conversation.id ? " active" : ""
                }`}
                onClick={() => setSelectedConversationId(conversation.id)}
              >
                <div className="conversation-item-top">
                  <strong>{conversation.title}</strong>
                  <span
                    className={`badge ${
                      conversation.latest_run_status === "waiting_approval"
                        ? "warning"
                        : conversation.latest_run_status === "blocked" ||
                            conversation.latest_run_status === "failed"
                          ? "danger"
                          : "success"
                    }`}
                  >
                    {conversation.pending_approval ? "approval" : conversation.latest_run_status}
                  </span>
                </div>
                <p className="muted conversation-preview">
                  {conversation.latest_message_preview || "No messages yet."}
                </p>
              </button>
            ))}
          </div>
        </aside>

        <section className="panel chat-main">
          <div className="chat-main-header">
            <div>
              <h3>{selectedConversation?.title ?? "New conversation"}</h3>
              <p className="muted">
                {selectedConversation
                  ? `${selectedConversation.spent_tokens} tokens / $${selectedConversation.spent_cost.toFixed(2)}`
                  : "Start a new guarded run."}
              </p>
            </div>
            <span className="badge">{selectedConversation?.latest_run_status ?? "idle"}</span>
          </div>

          {selectedConversation?.pending_approval && (
            <div className="approval-banner">
              <strong>Waiting for approval.</strong>
              <span>{selectedConversation.pending_approval_reason}</span>
            </div>
          )}

          <div className="chat-transcript" ref={transcriptRef}>
            {messages.length === 0 && (
              <div className="empty-chat">
                <p>Try a simple safe action first.</p>
                <pre>{`list files\nwrite file notes/demo.txt: hello\nsearch files for guarded`}</pre>
              </div>
            )}

            {messages.map((message) => (
              <article key={message.id} className={`chat-bubble ${message.role}`}>
                <header>
                  <span>{message.role}</span>
                </header>
                <div>
                  <p>{message.content}</p>
                </div>
              </article>
            ))}
          </div>

          <form className="chat-composer" onSubmit={handleSubmit}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={
                selectedConversation?.pending_approval
                  ? "This conversation is waiting for approval."
                  : "Ask the agent to use MCP tools..."
              }
              disabled={busy || selectedConversation?.pending_approval}
            />
            <div className="chat-composer-footer">
              <span className="muted">
                {selectedConversation?.pending_approval
                  ? "Approve or deny the pending tool call to continue this thread."
                  : "Multi-step runs can chain local and remote MCP tools in one conversation."}
              </span>
              <button
                className="button"
                disabled={busy || selectedConversation?.pending_approval || !draft.trim()}
              >
                {busy ? "Running..." : "Send"}
              </button>
            </div>
          </form>
        </section>
      </div>
    </>
  );
}
