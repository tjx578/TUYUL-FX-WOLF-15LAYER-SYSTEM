"use client";

import { FormEvent, useState } from "react";

export default function ViewerLoginForm() {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim() || submitting) return;

    setSubmitting(true);
    setError("");

    try {
      const response = await fetch("/api/set-session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token: token.trim() }),
        cache: "no-store",
      });

      if (!response.ok) {
        setError(
          response.status === 403
            ? "Token is valid but is not authorized for the viewer dashboard."
            : "The viewer session could not be validated.",
        );
        return;
      }

      setToken("");
      window.location.assign("/");
    } catch {
      setError("The authentication service is unavailable.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      <label
        htmlFor="viewer-token"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          color: "#cbd5e1",
          fontSize: 12,
          letterSpacing: "0.04em",
        }}
      >
        VIEWER JWT
        <input
          id="viewer-token"
          name="viewer-token"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Paste the temporary viewer token locally"
          required
          style={{
            width: "100%",
            boxSizing: "border-box",
            border: "1px solid #334155",
            borderRadius: 10,
            background: "#0f172a",
            color: "#f8fafc",
            padding: "13px 14px",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: 13,
            outline: "none",
          }}
        />
      </label>

      {error ? (
        <div
          role="alert"
          style={{
            border: "1px solid rgba(248,113,113,0.35)",
            borderRadius: 8,
            background: "rgba(127,29,29,0.22)",
            color: "#fecaca",
            padding: "10px 12px",
            fontSize: 12,
          }}
        >
          {error}
        </div>
      ) : null}

      <button
        type="submit"
        disabled={submitting || !token.trim()}
        style={{
          border: 0,
          borderRadius: 10,
          background: submitting || !token.trim() ? "#334155" : "#a3e635",
          color: submitting || !token.trim() ? "#94a3b8" : "#111827",
          cursor: submitting || !token.trim() ? "not-allowed" : "pointer",
          fontSize: 12,
          fontWeight: 800,
          letterSpacing: "0.08em",
          padding: "13px 16px",
        }}
      >
        {submitting ? "VALIDATING..." : "OPEN READ-ONLY DASHBOARD"}
      </button>

      <p
        style={{
          margin: 0,
          color: "#64748b",
          fontSize: 11,
          lineHeight: 1.6,
        }}
      >
        The token is submitted only to this same-origin service, validated by
        the core auth authority, and stored as an HttpOnly SameSite cookie.
        Never send a token through chat.
      </p>
    </form>
  );
}
