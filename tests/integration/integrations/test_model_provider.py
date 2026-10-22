"""Real SDK completion and streaming requests through a live-updated LLM broker."""

import json

from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering import supervisor_client
from brokering.brokers.llm_proxy.catalog import model_provider_catalog
from agent_core.providers._models import ChatDelta, ChatResponse
from agent_core.providers._openai import OpenAIProvider


async def test_model_requests_use_replaced_credentials_without_tool_grants(integration_app):
    seen = []

    async def models(request):
        assert request.headers.get("Authorization") == "Bearer old-local-key"
        return web.json_response({"object": "list", "data": [{"id": "local"}]})

    async def completion(request):
        body = await request.json()
        seen.append((request.headers.get("Authorization"), body))
        assert request.headers.get("x-api-key") is None
        if body.get("stream"):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            for delta, finish in [({"content": "After "}, None), ({"content": "reconnect"}, "stop")]:
                chunk = {
                    "id": "local",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "local",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
            await response.write(b"data: [DONE]\n\n")
            await response.write_eof()
            return response
        return web.json_response(
            {
                "id": "local",
                "object": "chat.completion",
                "created": 1,
                "model": "local",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Before reconnect"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    app = web.Application()
    app.router.add_get("/v1/models", models)
    app.router.add_post("/v1/chat/completions", completion)
    async with TestServer(app) as upstream:
        entry = model_provider_catalog()["llm_openai_compat"]
        async with integration_app({entry.slug: entry}) as h:

            async def rpc(verb, args):
                return await supervisor_client.call(verb, args, app_sock_path=h.supervisor.app_sock_path)

            added = await rpc(
                "add",
                {
                    "slug": entry.slug,
                    "kind": "model_provider",
                    "label": "Local model",
                    "auth_blob": {
                        "api_key": "old-local-key",
                        "base_url": str(upstream.make_url("/v1/")),
                    },
                },
            )
            provider = OpenAIProvider(proxy_socket=added["socket"])
            proc = h.supervisor._registry.get(entry.slug).broker.proc
            messages = [{"role": "user", "content": "Hello"}]
            try:
                assert [model.name for model in await provider.list_models()] == ["local"]
                before = await provider.chat(model="local", messages=messages)
                assert before.message.content == "Before reconnect"
                await rpc(
                    "reconnect",
                    {
                        "id": entry.slug,
                        "kind": "model_provider",
                        "auth_blob": {
                            "api_key": "new-local-key",
                            "base_url": str(upstream.make_url("/")),
                        },
                    },
                )
                assert h.supervisor._registry.get(entry.slug).broker.proc is proc
                # Reuse the same SDK client after the live credential update.
                chunks = [chunk async for chunk in provider.chat_stream(model="local", messages=messages)]
                assert (
                    "".join(chunk.content or "" for chunk in chunks if isinstance(chunk, ChatDelta))
                    == "After reconnect"
                )
                assert isinstance(chunks[-1], ChatResponse)
                assert chunks[-1].message.content == "After reconnect"
                assert [auth for auth, _ in seen] == ["Bearer old-local-key", "Bearer new-local-key"]
                assert all(body["messages"] == messages for _, body in seen)
                assert (await rpc("list", {"kind": "integration"}))["connections"] == []
                providers = (await rpc("list", {"kind": "model_provider"}))["connections"]
                assert [record["id"] for record in providers] == [entry.slug]
                assert not providers[0].get("operation_grants")
            finally:
                await provider._client.close()
