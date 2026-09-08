# WOLF15 Codex project settings

Start with the repository [AGENTS.md](../AGENTS.md) and the
[skill assessment](../docs/runbooks/codex-skill-assessment.md).

## Selection and availability

`config.toml` includes skill instructions and allows up to 10,000 tokens for the
catalog. This is a ceiling, not a promise to include all full instructions or a
measured reduction in cost. Global and plugin packages remain installed as before.

The assessment covers 220 entrypoints: 17 core, 145 conditional, 45 out of scope,
and 13 quarantined because referenced package resources are missing. AGENTS.md
instructs the assistant which to select. Categories are static fit decisions, not
behavioral certification or provider authentication results.

Project-local name-disable selectors were tested: config/read loaded 58 entries
from the project layer but skills/list still reported 167 enabled skills. A CLI
override disabled a matching name in a separate probe. The final project config
therefore does not use unproven disable selectors. Repository routing is an
instruction layer; it is not a technical disable or an execution security boundary.
The 53 curated-remote desktop skills are separate from standalone CLI discovery.

## Command permissions

`rules/settings-local.rules` has six prompt-only command families. The previous
19 auto-allow entries were removed, including free-form Python, pytest prefixes,
Railway, and Git stash. Root `settings.local.json` is now an inert legacy reference
with an empty allow list; Codex does not read it. The unrelated existing
`.claude/settings.local.json` is not edited.

Rules compare argv prefixes. A prompt can outrank an overlapping allow, but its
effective handling depends on the host, sandbox, approval mode, and managed policy.
With approval never, an interactive confirmation is not guaranteed. Alternate or
absolute executable paths, SDKs, and MCP tools require their own controls. No match
does not mean forbidden. These rules are not a production or broker firewall.

## Verification and adoption

Use a trusted checkout and a fresh Codex process to load project settings. Inspect
config/read origins and skills/list rather than inferring runtime behavior from
valid TOML. Reassess changed entrypoint hashes before relying on the dated matrix.
Do not rewrite vendor packages merely to satisfy a narrower local authoring linter.

The root Docker context excludes `.codex/`, `.agents/`, `.claude/`, and
`settings.local.json`; application `agents/` remains included. This was checked
against source context definitions, not a built image or deployed container.

No global package repair, global enablement change, production mutation, broker
operation, deployment, or automatic memory write is implied by this configuration.
