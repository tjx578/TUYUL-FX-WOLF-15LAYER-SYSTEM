# Codex local settings and skill discovery

## Which file does what

- `.codex/config.toml` is the native project configuration. It includes the skill instructions block and reserves the supported maximum of 10,000 tokens for the available-skills catalog. Catalog budgeting does not guarantee that every full skill instruction fits into a turn; Codex loads individual instructions as needed.
- `.codex/rules/settings-local.rules` contains 19 command-prefix permissions converted from the supplied list. Command permissions do not select or install skills.
- Root `settings.local.json` preserves 21 cleaned Claude Code permission entries as a reference. Codex does not consume this JSON. The existing `.claude/settings.local.json` is not modified.

## Coverage of skills

The project keeps automatic discovery from user, repository, system, and enabled plugin sources. It does not enumerate machine-specific skill paths or replace the user's `skills.config` or plugin settings. New installed skills therefore do not need a new permission entry in this repository. For portable repository skills, use `.agents/skills/<name>/SKILL.md`.

Global and desktop plugin skills stay in their installed locations; their source packages are not copied into this repository. The host's skill catalog remains authoritative for remote plugin skills. A standalone CLI app server and the desktop host can expose different catalogs.

A skill being discoverable does not prove that its external connector is authenticated, its tools are callable, its optional dependencies are installed, or its workflow has passed validation. This change does not enable every connector or automatically execute skills.

## Loading and local verification

Restart Codex in a trusted checkout. Project-local config and rules are skipped for an untrusted project. Trust is a local user setting, not a repository setting. During this audit, an already-trusted Windows repository needed its normalized drive-path alias added to the user's config; the private user config and backup are not committed.

Use the installed Codex app-server protocol to initialize a read-only client, then call `config/read` with `cwd` and `includeLayers: true`. Confirm that `skills.include_instructions` and `skills.max_context_tokens` originate from this project's `.codex` directory and no project layer is disabled. Call `skills/list` with `cwds` and `forceReload: true`; inspect `enabled`, errors, and coverage against the installed skill files. These requests do not start a model turn or execute a skill.

For a command-policy smoke check, run from the repository root:

```sh
codex execpolicy check --rules .codex/rules/settings-local.rules -- python -m pytest tests/test_orchestrator_state_manager.py -v
codex execpolicy check --rules .codex/rules/settings-local.rules -- git push
```

The first command should match an allow rule. The second should have no matching allow rule in this file. The checker evaluates argument lists without executing the target commands. Other global or managed rules can change the effective decision.

## Permission conversion and scope

Rules match argument prefixes, so additional trailing arguments can also match. The original Python stdin/inline-code, Railway, and Git stash command families retain their requested scope. In particular, Python `-` / `-c` allow arbitrary Python code, `railway variables` can include mutation subcommands, and `git stash` can include destructive subcommands. This is not a read-only or deny-by-default policy, and these entries are not needed merely to discover skills. Task-specific authorization still applies.

The two old machine-specific `find` entries use portable `rg --files` patterns now. The malformed Python `-c` wildcard is normalized. The missing historical temporary `repro_emit_gate.py` entry and nonexistent `test_signal_json_json_gate_adapter.py` argument were removed.

`Read(~/Downloads/**)` remains only in the Claude reference because it has no command-rule equivalent; filesystem policy is inherited. Bare `python` also remains only in that reference because a native `["python"]` prefix would match all Python commands. There is no blanket Bash or PowerShell allow rule. Shell wrappers and absolute executable paths can affect matching.

## Verification snapshot: 2026-09-09

Base: `773150952311db3dbf5188f36536b7837d8ec296`; Codex CLI: `0.153.4`.

| Evidence | Result |
| --- | --- |
| Native config loaded by app server with strict config parsing | Project origin confirmed for both skills settings; zero disabled layers |
| Global skill files compared with fresh `skills/list` | 157/157 present |
| Standalone app-server catalog | 167/167 enabled; 0 disabled; 0 parse errors |
| Additional skills in that runtime catalog | 10 skills from bundled/runtime plugins |
| Additional remote plugin skill files exposed by the desktop task | 53/53 readable across eight plugins |
| Remote plugin groups | Codex Security 15; Figma 12; Google Drive 5; OpenAI Developers 5; Remotion 12; Supabase 2; Deep Research 1; Plugin Management 1 |
| Local JSON/TOML validation and command-policy checks | 19 allowed patterns matched; 5 unrelated patterns not allowed; every referenced pytest file exists |
| Every skill workflow or external dependency executed | NOT_EXECUTED |

The remote desktop group is a separate evidence class from the standalone runtime catalog. Counts are a dated observation, not a fixed allow list or a guarantee about another machine. Local discovery validation does not establish production readiness.

## References

- [Codex skills](https://developers.openai.com/codex/skills)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference)
- [Codex rules](https://developers.openai.com/codex/rules)
- [Codex app-server protocol](https://developers.openai.com/codex/app-server)
