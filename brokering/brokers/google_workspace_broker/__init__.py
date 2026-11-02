"""Google Workspace API execution with supervisor-issued access credentials.

The supervisor owns OAuth renewal and encrypted persistence. This process gets
only the access token and scopes, never refresh tokens or client secrets. Token
rejection returns to the caller for coordinated renewal without tool replay.
"""
