"use client";

export default function GlobalError({ reset }: { reset: () => void }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#080c14",
          color: "#e1e8f2",
          fontFamily: "Inter, system-ui, sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: 480,
            padding: 32,
            borderRadius: 16,
            border: "1px solid rgba(255,255,255,0.1)",
            background: "#0e1420",
            textAlign: "center",
          }}
        >
          <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
            Application Error
          </h2>
          <p style={{ fontSize: 14, color: "#76aab8", marginBottom: 20 }}>
            Something went wrong. Please try again.
          </p>
          <button
            onClick={() => reset()}
            style={{
              padding: "8px 20px",
              borderRadius: 8,
              cursor: "pointer",
              border: "1px solid rgba(255,255,255,0.2)",
              background: "transparent",
              color: "#e1e8f2",
              fontSize: 14,
            }}
          >
            Retry
          </button>
        </div>
      </body>
    </html>
  );
}
