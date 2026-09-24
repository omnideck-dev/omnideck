"""Provider-neutral email processing shared by integration brokers.

Transport-specific clients such as IMAP and Gmail adapt their message parts
into the common MIME model; this package applies email semantics and renders
the best agent-readable body without exposing transport details.
"""
