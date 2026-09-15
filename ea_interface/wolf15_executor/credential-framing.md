# Runtime credential framing

The v1 wire layout remains eight ASCII decimal digits followed by exactly the
declared number of UTF-8 payload bytes (1 through 4096). The length is the
authoritative frame boundary. The client closes its handle after those bytes;
it neither probes EOF nor reads or parses later bytes on that connection. The
server emits one frame per connection. Persistent mode opens a new connection
for each handoff; it does not multiplex frames on one connection.

This explicitly replaces the former client-side no-trailing-bytes check. Bytes
inside the declared length must form exactly the canonical ordered JSON
envelope with the v1 schema, exact local bindings and valid credential shapes.
An extra field, reordered field, whitespace or suffix inside that length is
rejected. Data outside the frame cannot augment or override credential fields.
The canonical broker already writes this header and payload; its binary and
vault format require no change.

Header and payload share one 5000 ms monotonic read budget, starting after
FileOpen. Fragmented reads stay on the same handle. Deadline/stop checks reject
late read completion, but cannot preempt a blocked synchronous OS call. This
is not a hard wall-clock bound on FileOpen or an in-progress FileReadArray.

Offline regression tests cover framing, canonical comparison, bindings and
credential shapes with utility/I/O doubles. Compilation and CI do not prove
native credential handoff or persistent lifecycle acceptance. Config Freeze,
S5 and D0 Canary remain HOLD until their separate acceptance evidence exists.
