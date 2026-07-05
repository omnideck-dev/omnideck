"""Folds a list with repeated core add calls.

Each add is a nested invocation, so a long list exercises the per-root fanout
limit.
"""


def run(omni, args):
    total = 0
    for number in args["numbers"]:
        total = omni.invoke("omnideck.add@1", {"a": total, "b": number})["sum"]
    return {"total": total}
