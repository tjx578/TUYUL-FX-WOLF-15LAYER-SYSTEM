# Broker failure diagnostics

Failure stderr retains the existing reason code on its first line and appends:

```text
W15_BROKER_DIAGNOSTIC_V1 stage=VaultDecrypt exception=CryptographicException hresult=0x80090005
```

The example HRESULT is illustrative. Exit codes remain 2 for controlled rejection
and 3 for unexpected exceptions. Consumers should read the first line for the
legacy reason; consumers comparing all stderr must allow the second line.

Stages distinguish argument/identity validation, vault read/digest/decrypt/schema/
binding, envelope encoding, and pipe create/wait/header write/payload write/flush/
drain/dispose. The stage is the last operation entered, not proof of root cause.
An exception during cleanup can obscure an earlier exception. Exception categories
are a fixed allowlist; other types appear as `Exception`. No exception messages,
stack traces, inner exceptions, argument values, paths, or credentials are logged.
The broker remains single-threaded and fails closed; there is no retry or restart.

Windows packaging CI executes synthetic argument, missing-file, and invalid-DPAPI
cases against the built EXE, including a persistent-mode client connection.
These tests do not establish MT5 compatibility or lifecycle acceptance.

For a separately authorized acceptance run, correlate stderr with the CI commit,
EXE checksum, process ID/start time and terminal timestamps. Preserve failed runs.
R1/R2 are historical failures; this diagnostic change does not retroactively pass
them or establish their exact root cause. Do not log vault contents to investigate.
