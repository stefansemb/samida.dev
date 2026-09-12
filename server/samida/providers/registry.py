from dataclasses import dataclass

from samida.providers.anthropic import AnthropicProvider
from samida.providers.base import ModelProvider
from samida.providers.image_base import ImageProvider
from samida.providers.image_flux import FluxProvider
from samida.providers.image_gemini import NanoBananaProvider
from samida.providers.image_openai import GptImageProvider
from samida.providers.image_pollinations import PollinationsProvider
from samida.providers.openai import OpenAIProvider


@dataclass(frozen=True)
class ChatProviderSpec:
    provider_class: type[ModelProvider]
    default_base_url: str
    default_model: str


CHAT_PROVIDER_SPECS: dict[str, ChatProviderSpec] = {
    "openai": ChatProviderSpec(
        provider_class=OpenAIProvider,
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-5.6-luna",
    ),
    "anthropic": ChatProviderSpec(
        provider_class=AnthropicProvider,
        default_base_url="https://api.anthropic.com/v1",
        default_model="claude-opus-5",
    ),
}


@dataclass(frozen=True)
class ImageProviderSpec:
    provider_class: type[ImageProvider]
    default_base_url: str
    default_model: str


IMAGE_PROVIDER_SPECS: dict[str, ImageProviderSpec] = {
    "gpt_image": ImageProviderSpec(
        provider_class=GptImageProvider,
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-image-1",
    ),
    "flux": ImageProviderSpec(
        provider_class=FluxProvider,
        default_base_url="https://api.bfl.ai",
        default_model="flux-pro-1.1",
    ),
    "nano_banana": ImageProviderSpec(
        provider_class=NanoBananaProvider,
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-2.5-flash-image",
    ),
    # Free and keyless by default — it's the automatic fallback when none of
    # the paid providers above are configured (see
    # ImageProviderFactory.build_default()). Listed here too so a user can
    # *optionally* add a free Pollinations token in Settings, which removes
    # the watermark that anonymous requests get.
    "pollinations": ImageProviderSpec(
        provider_class=PollinationsProvider,
        default_base_url="https://image.pollinations.ai",
        default_model="flux",
    ),
}

# Preference order when the agent needs "the" image provider for a user who
# may have more than one configured (the generate_image tool takes no
# provider argument — it just uses whichever the user has set up first).
# "pollinations" is deliberately excluded: it's never "preferred" over a paid
# provider — it's the fallback tried only once none of these are configured.
IMAGE_PROVIDER_PREFERENCE: list[str] = ["gpt_image", "flux", "nano_banana"]
