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

`rules/settings-local.rules` has eight prompt-only command families. The previous
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

## Precision checks and project defaults

The project defaults are `approval_policy = "on-request"` and
`sandbox_mode = "workspace-write"`. They are scoped to this trusted project;
host overrides and managed constraints still determine effective permissions.
Merge these root keys with local changes instead of replacing a local config
that contains MCP or other machine-specific settings. Global configuration is
not changed. Model, provider, skills and network settings are unchanged.

The rules preserve the original 29 launcher spellings and cover 70 spellings in
eight families. Inline positive and negative examples are checked by the native
Codex parser. This is not universal executable coverage: absolute paths, aliases,
case variants, shell expansion and other tool surfaces need separate assessment.

From the repository root, using inspected Python and Codex executable paths:

```powershell
python .codex/verify_execpolicy.py --codex <codex-executable> --rules .codex/rules/settings-local.rules --output native-local.json
```

The verifier runs only `codex --version` and `codex execpolicy check`. Target
commands are test data and are never executed. Repeat `--rules` to include
identified user/team rule files. Explicitly supplied files do not prove the
same files are loaded in a desktop session; verify origins and trust in a fresh
session before adoption. No-match is not a deny decision. Native checks do not
measure prompt frequency, development accuracy or application security.
