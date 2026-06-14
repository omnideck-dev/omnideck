"""One Pydantic model per tool — the single source of truth for tool typing.

A tool's signature is turned into a single Pydantic model. That model drives
both directions:

- **Outbound:** its JSON Schema is what providers advertise to the LLM.
- **Inbound:** its validation coerces the LLM's argument JSON back into typed
  Python values before the call.

This collapses what used to be two independent annotation walkers (an outbound
schema generator and an inbound coercer) plus a third hidden one inside the
Ollama client into Pydantic's single, well-tested implementation.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator

from ._docstrings import parse_arg_descriptions

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Built models are cached per function. Factory-created tools are fresh function
# objects each build, so a weak-keyed cache lets collected tools drop out.
_MODEL_CACHE: WeakKeyDictionary[Callable[..., Any], type[BaseModel]] = WeakKeyDictionary()


def tool_model(func: Callable[..., Any]) -> type[BaseModel]:
    """Return (building and caching on first use) the Pydantic model for *func*.

    Each parameter becomes a model field: its annotation is the field type, its
    docstring ``Args:`` entry the field description, and its default — if any —
    the field default (so a param without a default is a required field).
    """
    model = _MODEL_CACHE.get(func)
    if model is None:
        model = _build_model(func)
        _MODEL_CACHE[func] = model
    return model


def parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build the JSON Schema for *func*'s parameters (the tool ``parameters``).

    Post-processed to the shape the providers expect: ``title`` and ``default``
    keys dropped, and ``None`` removed from unions (optionality is carried by
    ``required``, not the type) so ``Optional[T]`` collapses to ``T``.
    """
    schema = tool_model(func).model_json_schema()
    schema.pop("title", None)
    _clean(schema)
    # Pydantic omits these when empty; keep a stable object shape for providers.
    schema.setdefault("properties", {})
    schema.setdefault("required", [])
    return schema


def validate_arguments(
    func: Callable[..., Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    """Validate/coerce raw LLM *arguments* against *func*'s signature.

    Returns a kwargs dict of typed values ready to splat into the call. Raises
    ``ValueError`` naming the offending parameter so the model gets a corrective
    message on retry.
    """
    model = tool_model(func)
    try:
        instance = model.model_validate(arguments)
    except ValidationError as exc:
        raise ValueError(_format_error(func, exc)) from exc
    return {name: getattr(instance, name) for name in model.model_fields}


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------


def _build_model(func: Callable[..., Any]) -> type[BaseModel]:
    # eval_str resolves string annotations from ``from __future__ import
    # annotations`` modules to real types; without it every such param's
    # annotation stays a string and the field type is meaningless.
    sig = inspect.signature(func, eval_str=True)
    descriptions = parse_arg_descriptions(inspect.getdoc(func))

    fields: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        # *args / **kwargs have no fixed schema; skip them.
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else Any
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, Field(default, description=descriptions.get(name)))

    return create_model(
        func.__name__,
        # protected_namespaces=() so a param named e.g. ``model_name`` doesn't
        # trip Pydantic's reserved-prefix guard.
        __config__=ConfigDict(protected_namespaces=()),
        __validators__={
            "_decode_json_strings": model_validator(mode="before")(
                classmethod(_decode_json_strings)
            )
        },
        **fields,
    )


def _decode_json_strings(cls: type[BaseModel], data: Any) -> Any:
    """Decode JSON strings the model sends for object-typed parameters.

    Providers already JSON-decode the top-level argument blob, but a model will
    sometimes double-encode a nested object/array as a string. Pydantic won't
    parse a string into a model on its own, so for fields whose type is a model
    (or a list of models) we decode a string value first.
    """
    if not isinstance(data, dict):
        return data
    decoded: dict[str, Any] | None = None
    for name, field in cls.model_fields.items():
        if name not in data:
            continue
        value = data[name]
        target = _json_string_target(field.annotation)
        if target == "model" and isinstance(value, str):
            new_value: Any = _try_json(value)
        elif target == "list" and isinstance(value, list):
            new_value = [_try_json(v) if isinstance(v, str) else v for v in value]
        else:
            continue
        if new_value is not value:
            if decoded is None:
                decoded = dict(data)
            decoded[name] = new_value
    return decoded if decoded is not None else data


def _json_string_target(annotation: Any) -> str | None:
    """Classify *annotation* for JSON-string decoding: "model", "list", or None.

    Only model-typed and list-of-model parameters need the leniency; everything
    else is left to Pydantic.
    """
    annotation = _strip_optional(annotation)
    if _is_model(annotation):
        return "model"
    if get_origin(annotation) is list:
        args = get_args(annotation)
        if args and _is_model(_strip_optional(args[0])):
            return "list"
    return None


def _strip_optional(annotation: Any) -> Any:
    if get_origin(annotation) is Union:
        members = [a for a in get_args(annotation) if a is not type(None)]
        if len(members) == 1:
            return members[0]
    return annotation


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _try_json(value: str) -> Any:
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


# ---------------------------------------------------------------------------
# Schema post-processing
# ---------------------------------------------------------------------------


def _clean(node: Any) -> Any:
    """Recursively strip Pydantic noise and normalize unions in place.

    - Drops ``title`` (Pydantic adds one per field) and ``default`` to keep the
      schema lean and stable.
    - Removes ``{"type": "null"}`` from ``anyOf``; if a single member remains the
      union collapses to it, preserving any sibling ``description``.
    """
    if isinstance(node, dict):
        node.pop("title", None)
        node.pop("default", None)
        # additionalProperties: true is the JSON-Schema default — drop it so a
        # bare ``dict`` / ``dict[str, Any]`` reads as a plain object. A typed
        # value (``dict[str, str]``) keeps its schema and is left alone.
        if node.get("additionalProperties") is True:
            node.pop("additionalProperties")
        if "anyOf" in node:
            members = [m for m in node["anyOf"] if not _is_null(m)]
            if len(members) == 1:
                only = _clean(members[0])
                description = node.get("description")
                node.clear()
                node.update(only)
                if description is not None:
                    node["description"] = description
                return node
            node["anyOf"] = [_clean(m) for m in members]
        for key, value in node.items():
            if key != "anyOf":
                _clean(value)
    elif isinstance(node, list):
        for item in node:
            _clean(item)
    return node


def _is_null(member: Any) -> bool:
    return isinstance(member, dict) and member.get("type") == "null"


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------


def _format_error(func: Callable[..., Any], exc: ValidationError) -> str:
    """Turn a Pydantic ValidationError into a single, parameter-named message."""
    func_name = getattr(func, "__name__", repr(func))
    errors = exc.errors()
    if not errors:  # pragma: no cover - ValidationError always has errors
        return f"Invalid arguments for tool '{func_name}': {exc}"
    first = errors[0]
    loc = first.get("loc", ())
    name = str(loc[0]) if loc else "?"
    if first.get("type") == "missing":
        return f"Required parameter '{name}' is missing for tool '{func_name}'"
    msg = first.get("msg", "invalid value")
    return f"Invalid value for parameter '{name}' of tool '{func_name}': {msg}"
