"""Google-style docstring parsing for tool functions.

A leaf module with no internal dependencies: both the schema builder and the
model builder read a tool's docstring for the model-facing description and the
per-parameter descriptions, so the parsing lives one layer down where either
side can depend on it without a cycle.
"""

import re

# Matches a Google-style arg line: leading whitespace, param name, colon,
# then optional type in parens, then the description.
_ARG_LINE_RE = re.compile(
    r"^\s{4,}(\w+)"          # indented param name
    r"(?:\s*\([^)]*\))?"     # optional (type) — we already know the type
    r"\s*:\s*"               # colon separator
    r"(.+)",                 # description text
)

# Section header prefixes that end the description body (case-insensitive).
_SECTION_PREFIXES = (
    "args:", "arguments:", "returns:", "raises:", "yields:",
    "note:", "notes:", "examples:", "example:",
)


def parse_arg_descriptions(docstring: str | None) -> dict[str, str]:
    """Extract per-parameter descriptions from a Google-style docstring.

    Args:
        docstring: The raw docstring text (may be None).

    Returns:
        Mapping of parameter name to its description string.
    """
    if not docstring:
        return {}

    descriptions: dict[str, str] = {}
    lines = docstring.split("\n")
    in_args = False
    current_param: str | None = None
    current_desc_parts: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Detect start of Args section
        if stripped in ("Args:", "Arguments:"):
            in_args = True
            continue

        # Detect end of Args section (another section header or blank after content)
        if in_args and stripped and stripped.endswith(":") and not stripped.startswith(" "):
            # Save any in-progress param
            if current_param is not None:
                descriptions[current_param] = " ".join(current_desc_parts).strip()
            break

        if not in_args:
            continue

        # Try matching a new arg line
        m = _ARG_LINE_RE.match(line)
        if m:
            # Save previous param
            if current_param is not None:
                descriptions[current_param] = " ".join(current_desc_parts).strip()
            current_param = m.group(1)
            current_desc_parts = [m.group(2).strip()]
        elif current_param is not None and stripped:
            # Continuation line for current param
            current_desc_parts.append(stripped)

    # Save last param
    if current_param is not None:
        descriptions[current_param] = " ".join(current_desc_parts).strip()

    return descriptions


def extract_description(docstring: str | None) -> str:
    """Extract the full description text from a Google-style docstring.

    Returns everything before the first section header (Args, Returns, etc.),
    collapsed into a single paragraph.
    """
    if not docstring:
        return ""
    lines: list[str] = []
    for line in docstring.strip().splitlines():
        if line.strip().lower().startswith(_SECTION_PREFIXES):
            break
        lines.append(line.strip())
    # Collapse into a single string, dropping empty lines at boundaries.
    return " ".join(part for part in lines if part)
