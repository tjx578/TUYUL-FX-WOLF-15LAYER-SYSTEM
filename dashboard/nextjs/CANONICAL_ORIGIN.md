# Owner-login canonical origin

Set server-only `DASHBOARD_CANONICAL_ORIGIN` to one browser origin. Local direct testing uses `http://127.0.0.1:3000`; a public deployment uses its actual HTTPS origin. No fallback to request URL, Host, Forwarded or X-Forwarded-* is permitted. Missing/invalid configuration returns 503; missing/invalid/mismatched incoming Origin returns 403 before body parsing or upstream credentials. Matching Origin with empty JSON reaches 400 body validation.

`HOSTNAME=0.0.0.0` is only the bind address. The proxy must preserve external host/protocol and overwrite client-supplied forwarding headers at its trust boundary, but those headers do not authorize login. The handler compares against configured canonical origin instead of reconstructing authority from untrusted headers. Proxy routing/access restrictions are separate controls.

Only HTTPS is accepted for public origins; HTTP is accepted only for exact localhost, 127.0.0.1 or [::1]. Credentials, wildcard/bind hosts, paths, query/fragment and ambiguous serialized origins are rejected. Scheme/hostname/default port are normalized; nondefault ports remain significant.

Optional non-production `DASHBOARD_ORIGIN_DIAGNOSTICS=1` logs at most five sanitized origin records per process. Only validated origins/host representations and enum protocols are logged, never raw headers, bodies, passwords, tokens or cookies. Production never enables this log even if the flag is set.

Threat model: cross-site attackers may control Origin/Host/forwarded headers in direct HTTP clients. Those headers cannot modify the configured allowlist. Origin is a browser CSRF boundary, not credential authentication: password verification, upstream authorization, session validation and existing viewer scope remain required. No production deployment or proxy configuration is performed by this revision.

Verification order: handler/local-origin diagnostics; isolated proxy-origin diagnostics including forged forwarding headers; new image build and full smoke. Earlier failed evidence stays terminal. ACL and dependencies are outside this fix.
