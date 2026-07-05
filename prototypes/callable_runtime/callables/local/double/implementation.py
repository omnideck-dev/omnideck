"""Doubles a value by invoking the core add callable through the parent."""


def run(omni, args):
    doubled = omni.invoke("omnideck.add@1", {"a": args["value"], "b": args["value"]})
    return {"result": doubled["sum"]}
