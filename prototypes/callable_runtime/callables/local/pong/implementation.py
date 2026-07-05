"""Other half of the mutual-recursion pair."""


def run(omni, args):
    return omni.invoke("local.ping@1", args)
