"""Exercises the prototype callable runtime end to end.

Each scenario invokes a callable as if the agent called it, then checks the
result or the structured error code against what the design predicts. Run:

    python3 demo.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import runtime

CALLABLES = Path(__file__).parent / "callables"

_passed = 0
_failed = 0


async def _invoke(ref, args):
    ctx, g = runtime.new_agent_context(ref)
    reg = runtime.Registry.load(CALLABLES)
    try:
        result = await runtime.invoke_callable(reg, ref, args, ctx, g)
        return {"ok": True, "result": result}, g
    except runtime.CallableError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}, g


async def scenario(title, ref, args, *, expect_result=None, expect_code=None, trace=False):
    global _passed, _failed
    outcome, g = await _invoke(ref, args)

    if expect_code is not None:
        ok = (not outcome["ok"]) and outcome["code"] == expect_code
        got = outcome.get("code") if not outcome["ok"] else f"ok:{outcome['result']}"
        want = f"error {expect_code}"
    else:
        ok = outcome["ok"] and outcome["result"] == expect_result
        got = outcome["result"] if outcome["ok"] else f"error {outcome.get('code')}"
        want = expect_result

    mark = "PASS" if ok else "FAIL"
    if ok:
        _passed += 1
    else:
        _failed += 1
    print(f"[{mark}] {title}")
    print(f"       invoke {ref} {args}")
    print(f"       want: {want}")
    print(f"       got:  {got}")
    if trace:
        print("       call tree:")
        for ev in g.events:
            if ev["type"] == "callable_started":
                indent = "  " * ev["depth"]
                print(f"         {indent}-> {ev['ref']} ({ev['scope']})")
            elif ev["type"] == "dependency_call":
                print(f"           {ev['from']} calls {ev['target']}")
    print()


async def main():
    print("Callable runtime prototype\n")

    # Happy path: agent invokes a core callable directly, in-process.
    await scenario("core in-process", "omnideck.add@1", {"a": 2, "b": 3},
                   expect_result={"sum": 5})

    # A local callable runs in a subprocess and calls a core dependency.
    await scenario("subprocess local -> core dependency", "local.double@1", {"value": 21},
                   expect_result={"result": 42}, trace=True)

    # A local callable calls another local callable, which calls core.
    await scenario("local -> local -> core (depth 3)", "local.nested@1", {"value": 5},
                   expect_result={"result": 11}, trace=True)

    # Fanout within limit: a loop calling a dependency a few times.
    await scenario("bounded fanout", "local.sum_list@1", {"numbers": [1, 2, 3, 4]},
                   expect_result={"total": 10})

    # Fanout over the per-root child-call cap (64).
    await scenario("fanout cap enforced", "local.sum_list@1", {"numbers": list(range(70))},
                   expect_code="CALL_GRAPH_FANOUT_EXCEEDED")

    # Two callables calling each other trips recursion detection.
    await scenario("recursion rejected", "local.ping@1", {},
                   expect_code="CALL_GRAPH_RECURSION")

    # A callable that invokes a dependency it never declared is refused.
    await scenario("undeclared dependency refused", "local.sneaky@1", {},
                   expect_code="UNDECLARED_DEPENDENCY")

    # Bad input is caught at the boundary before the callable runs.
    await scenario("input schema validated", "local.double@1", {"value": "not a number"},
                   expect_code="VALIDATION_ERROR")

    print(f"{_passed} passed, {_failed} failed")
    raise SystemExit(1 if _failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
