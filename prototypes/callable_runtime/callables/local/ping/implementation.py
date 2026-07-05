"""Half of a mutual-recursion pair; the runtime should refuse the cycle."""


def run(omni, args):
    return omni.invoke("local.pong@1", args)
