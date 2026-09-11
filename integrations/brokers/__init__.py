"""Long-lived subprocesses that isolate credentials and upstream protocols.

Each concrete broker lives in its own sub-package (for example
``email_broker``, ``google_workspace_broker``, or ``llm_proxy``) and is
launched as ``python -m integrations.brokers.<name>``. Shared authorization,
UDS lifecycle, readiness, and exit-code infrastructure lives in
``integrations.brokers._common``.
"""
