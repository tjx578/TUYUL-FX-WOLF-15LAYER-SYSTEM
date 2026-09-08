"use client";

import { FormEvent, useState } from "react";

export default function ViewerLoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password || submitting) return;

    setSubmitting(true);
    setError("");

    try {
      const response = await fetch("/api/auth/owner-login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
        cache: "no-store",
      });

      if (!response.ok) {
        setError(
          response.status === 401
            ? "Username or password is incorrect."
            : response.status === 429
              ? "Too many login attempts. Wait one minute and try again."
            : "The viewer session could not be created.",
        );
        return;
      }

      setPassword("");
      window.location.assign("/");
    } catch {
      setError("The authentication service is unavailable.");
    } finally {
      setPassword("");
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
        htmlFor="owner-username"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          color: "#cbd5e1",
          fontSize: 12,
          letterSpacing: "0.04em",
        }}
      >
        OWNER USERNAME
        <input
          id="owner-username"
          name="username"
          type="text"
          autoComplete="username"
          maxLength={254}
          spellCheck={false}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          placeholder="Owner account"
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

      <label
        htmlFor="owner-password"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          color: "#cbd5e1",
          fontSize: 12,
          letterSpacing: "0.04em",
        }}
      >
        PASSWORD
        <input
          id="owner-password"
          name="password"
          type="password"
          autoComplete="current-password"
          maxLength={1024}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          style={{
            width: "100%",
            boxSizing: "border-box",
            border: "1px solid #334155",
            borderRadius: 10,
            background: "#0f172a",
            color: "#f8fafc",
            padding: "13px 14px",
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
        disabled={submitting || !username.trim() || !password}
        style={{
          border: 0,
          borderRadius: 10,
          background: submitting || !username.trim() || !password ? "#334155" : "#a3e635",
          color: submitting || !username.trim() || !password ? "#94a3b8" : "#111827",
          cursor: submitting || !username.trim() || !password ? "not-allowed" : "pointer",
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
        Credentials are sent only to this same-origin service. A short-lived
        read-only session is stored in an HttpOnly SameSite cookie; the JWT is
        never exposed to browser JavaScript.
      </p>
    </form>
  );
}
