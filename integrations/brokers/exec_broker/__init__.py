"""Generic CLI-exec integration broker.

One process per configured integration. Each instance is scoped to a single
binary or script the user configured at add-time — the agent supplies only
the arguments, never the binary. The secret(s) the integration needs live in
this process's own environment and are never returned to the caller;
anything that leaks into the child process's stdout/stderr is redacted
before the RPC response goes out.
"""
