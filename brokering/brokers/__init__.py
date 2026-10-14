"""Long-lived subprocesses that isolate credentials and upstream protocols.

Each concrete broker lives in its own sub-package (for example
``email_broker``, ``google_workspace_broker``, or ``llm_proxy``) and is
launched as ``python -m brokering.brokers.<name>``. Integration brokers share the
operation-grant dispatcher in ``brokering.brokers._common``; the LLM proxy
does not depend on integration operations. Transport, readiness, and process
lifecycle primitives live in the parent ``brokering`` package.

Keep this package initializer free of broker imports so clients can load one
implementation without importing the other domains.
"""
