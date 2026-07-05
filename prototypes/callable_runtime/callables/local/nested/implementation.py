"""Calls another local callable, which itself calls a core callable.

This proves a subprocess runner can depend on another subprocess runner, with
the parent brokering both hops.
"""


def run(omni, args):
    doubled = omni.invoke("local.double@1", {"value": args["value"]})
    return {"result": doubled["result"] + 1}
