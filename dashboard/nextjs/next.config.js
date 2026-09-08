/* eslint-disable @typescript-eslint/no-require-imports -- Next config is CommonJS. */
const path = require("path");
const production = process.env.NODE_ENV === "production";
const rawApi = process.env.INTERNAL_API_URL?.trim();
if (production && !rawApi) throw new Error("INTERNAL_API_URL is required for the Railway dashboard server.");
if (rawApi) {
  let url;
  try { url = new URL(rawApi); } catch { throw new Error("INTERNAL_API_URL must be a valid origin."); }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password ||
      url.pathname !== "/" || url.search || url.hash || (production && url.protocol !== "https:")) {
    throw new Error("INTERNAL_API_URL must be a credential-free HTTPS origin in production.");
  }
}

/** Railway is the only frontend target. Upstream origins stay server-only. */
module.exports = {
  reactStrictMode: true,
  output: "standalone",
  outputFileTracingRoot: __dirname,
  webpack(config) {
    config.resolve.alias["@"] = path.join(__dirname, "src");
    return config;
  },
  async headers() {
    return [{ source: "/(.*)", headers: [
      { key: "Content-Security-Policy", value: [
        "default-src 'self'", "connect-src 'self'", "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com", "img-src 'self' data:",
        "script-src 'self' 'unsafe-inline'" + (production ? "" : " 'unsafe-eval'"),
        "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'",
      ].join("; ") },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    ] }];
  },
  // The runtime proxy owns authentication and the three exact GET projections.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: false },
};
