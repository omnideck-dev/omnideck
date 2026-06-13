"""Build OpenAI-style tool JSON schemas from Python callables.

Needed by the providers that require an explicit schema to advertise a tool
(OpenAI, Anthropic, Ollama). The parameter schema itself comes from the tool's
Pydantic model, so the schema sent to the model and the validation applied to
its reply share one definition.
"""

import inspect
import json
import logging
from collections.abc import Callable
from typing import Any

from ._docstrings import extract_description
from ._tool_model import parameters_schema

# Match the context estimator.
_CHARS_PER_TOKEN = 4

logger = logging.getLogger(__name__)


def callable_to_json_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Convert a Python callable into an OpenAI-style tool JSON schema.

    Args:
        func: The callable to convert.

    Returns:
        A dict matching the OpenAI tool schema format.
    """
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": extract_description(inspect.getdoc(func)),
            "parameters": parameters_schema(func),
        },
    }


def estimate_tool_tokens(func: Callable[..., Any]) -> int:
    """Estimate the token cost of including *func*'s schema in a chat request."""
    schema = callable_to_json_schema(func)
    chars = len(json.dumps(schema, default=str))
    return chars // _CHARS_PER_TOKEN
