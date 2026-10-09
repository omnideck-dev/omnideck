"""Credential brokering for tool integrations and model-provider connections.

Clients import ``broker_client`` for operation RPCs or ``supervisor_client``
for connection management. Model traffic uses the separate HTTP LLM proxy.
Importing this package does not initialize the supervisor or load catalogs.
"""
