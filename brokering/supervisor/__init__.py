"""Supervisor: the credential-owning trusted process.

Runs as a dedicated UID, holds the master key for the credential vault, and
spawns + manages tool-integration brokers and model-provider HTTP proxies. The app server
communicates with the supervisor over a Unix Domain Socket to add, list,
resolve, and remove connections, but never reads the decrypted credentials
itself.
"""
