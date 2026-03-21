"use client";

import { useState } from "react";
import Button from "@/components/ui/Button";
import type { AgentItem } from "@/types/agent-manager";
import type { LockAgentRequest } from "@/types/agent-manager";

interface Props {
  agent: AgentItem | null;
  onLock: (agentId: string, data: LockAgentRequest) => Promise<{ success: boolean; error?: string }>;
  onUnlock: (agentId: string) => Promise<{ success: boolean; error?: string }>;
  onToggleSafeMode: (agentId: string, current: boolean) => Promise<{ success: boolean; error?: string }>;
  onDelete: (agentId: string) => Promise<{ success: boolean; error?: string }>;
}

export function AgentManagerActions({ agent, onLock, onUnlock, onToggleSafeMode, onDelete }: Props) {
  const [lockLoading, setLockLoading] = useState(false);
  const [safeModeLoading, setSafeModeLoading] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "ok" | "error"; text: string } | null>(null);
  const [showLockPrompt, setShowLockPrompt] = useState(false);
  const [lockReason, setLockReason] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  if (!agent) {
    return (
      <div style={{ padding: 8, color: "var(--text-muted)", fontSize: 11 }}>
        Select an agent to perform actions.
      </div>
    );
  }

  const setMsg = (type: "ok" | "error", text: string) => {
    setFeedback({ type, text });
    setTimeout(() => setFeedback(null), 4000);
  };

  const handleLockToggle = async () => {
    if (agent.locked) {
      // Unlock immediately
      setLockLoading(true);
      const result = await onUnlock(agent.id);
      setLockLoading(false);
      setMsg(result.success ? "ok" : "error", result.success ? "Agent unlocked" : (result.error ?? "Unlock failed"));
    } else {
      // Show lock prompt
      setShowLockPrompt(true);
    }
  };

  const cancelLock = () => {
    setShowLockPrompt(false);
    setLockReason("");
  };

  const confirmLock = async () => {
    if (!lockReason.trim()) return;
    setShowLockPrompt(false);
    setLockLoading(true);
    const result = await onLock(agent.id, { reason: lockReason.trim() });
    setLockLoading(false);
    setLockReason("");
    setMsg(result.success ? "ok" : "error", result.success ? "Agent locked" : (result.error ?? "Lock failed"));
  };

  const handleSafeMode = async () => {
    setSafeModeLoading(true);
    const result = await onToggleSafeMode(agent.id, agent.safe_mode);
    setSafeModeLoading(false);
    setMsg(
      result.success ? "ok" : "error",
      result.success
        ? `Safe mode ${agent.safe_mode ? "disabled" : "enabled"}`
        : (result.error ?? "Toggle failed")
    );
  };

  const confirmDelete = async () => {
    setShowDeleteConfirm(false);
    setDeleteLoading(true);
    const result = await onDelete(agent.id);
    setDeleteLoading(false);
    setMsg(result.success ? "ok" : "error", result.success ? "Agent deleted" : (result.error ?? "Delete failed"));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Action Buttons */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {/* Lock / Unlock */}
        <Button
          variant={agent.locked ? "primary" : "ghost"}
          onClick={handleLockToggle}
          disabled={lockLoading}
        >
          {lockLoading ? "..." : agent.locked ? "UNLOCK" : "LOCK"}
        </Button>

        {/* Safe Mode Toggle */}
        <Button
          variant={agent.safe_mode ? "primary" : "ghost"}
          onClick={handleSafeMode}
          disabled={safeModeLoading}
        >
          {safeModeLoading ? "..." : agent.safe_mode ? "DISABLE SAFE MODE" : "ENABLE SAFE MODE"}
        </Button>

        {/* Delete */}
        <Button
          variant="danger"
          onClick={() => setShowDeleteConfirm(true)}
          disabled={deleteLoading}
        >
          {deleteLoading ? "Deleting..." : "DELETE"}
        </Button>
      </div>

      {/* Feedback */}
      {feedback && (
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: feedback.type === "ok" ? "var(--green)" : "var(--red)",
          }}
        >
          {feedback.text}
        </span>
      )}

      {/* Lock Reason Prompt */}
      {showLockPrompt && (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            border: "1px solid var(--bg-border)",
            background: "var(--bg-card)",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <span style={{ fontSize: 11, color: "var(--text-secondary)", fontWeight: 600 }}>
            Lock reason:
          </span>
          <input
            type="text"
            value={lockReason}
            onChange={(e) => setLockReason(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && confirmLock()}
            placeholder="Enter reason for locking..."
            style={{
              fontSize: 12,
              padding: "6px 10px",
              borderRadius: 6,
              border: "1px solid var(--bg-border)",
              background: "rgba(255,255,255,0.05)",
              color: "var(--text-primary)",
              outline: "none",
            }}
            autoFocus
          />
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="danger" onClick={confirmLock} disabled={!lockReason.trim()}>
              CONFIRM LOCK
            </Button>
            <Button variant="ghost" onClick={cancelLock}>
              CANCEL
            </Button>
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      {showDeleteConfirm && (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            border: "1px solid rgba(239, 68, 68, 0.3)",
            background: "rgba(239, 68, 68, 0.06)",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <span style={{ fontSize: 11, color: "var(--red)", fontWeight: 600 }}>
            Delete agent <strong>{agent.agent_name}</strong>? This cannot be undone.
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="danger" onClick={confirmDelete}>
              CONFIRM DELETE
            </Button>
            <Button variant="ghost" onClick={() => setShowDeleteConfirm(false)}>
              CANCEL
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
