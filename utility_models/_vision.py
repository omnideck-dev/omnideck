"""Describe images with the vision utility model."""

from typing import Any

from ._calls import prepare_utility_call


async def vision_generate(
    prompt: str,
    image_base64: str,
    *,
    media_type: str = "image/png",
) -> str:
    """Send an image and a prompt to the vision model set in settings.

    Args:
        prompt: Question or instruction about the image.
        image_base64: Base64-encoded image data.
        media_type: MIME type of the image.

    Returns:
        The model's text response.

    Raises:
        ValueError: If no vision provider/model is configured.
        ProviderError: If the provider call fails.
    """
    call = await prepare_utility_call("vision")
    if call is None:
        msg = "No vision model configured. Set one in Settings > System."
        raise ValueError(msg)

    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": prompt,
        "images": [{"data": image_base64, "media_type": media_type}],
    }]
    response = await call.client.chat(
        model=call.model,
        messages=messages,
        options=call.options,
        think=call.think,
        model_info=call.model_info,
    )
    return response.message.content or ""
