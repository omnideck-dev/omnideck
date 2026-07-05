"""Tries to invoke a callable it did not declare as a dependency.

callable_dependencies is empty, so the parent refuses the invoke_dependency
request. Declaring dependencies is the enforced allow-list, not a hint.
"""


def run(omni, args):
    result = omni.invoke("omnideck.add@1", {"a": 1, "b": 2})
    return {"sum": result["sum"]}
