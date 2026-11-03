"""Common agent guidance when a tool's completion cannot be established."""


UNKNOWN_OUTCOME = (
    "The remote action may have completed, including partial changes. "
    "Check the service before retrying; do not repeat the action until its outcome is verified."
)
