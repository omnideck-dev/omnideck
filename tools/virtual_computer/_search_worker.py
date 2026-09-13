"""Isolated grep worker; stream bounded matches so timeouts retain progress."""

import json
import sys

from .models import GrepMatch
from .search_ops import _search


def _emit_match(match: GrepMatch) -> None:
    print(json.dumps({"match": match.model_dump()}), flush=True)


def main() -> None:
    """Run one search supplied on stdin and emit its completion metadata."""
    arguments = json.load(sys.stdin)
    result = _search(**arguments, on_match=_emit_match)
    print(json.dumps({"result": result.model_dump(exclude={"matches"})}), flush=True)


if __name__ == "__main__":
    main()
