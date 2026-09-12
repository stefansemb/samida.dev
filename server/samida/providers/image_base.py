from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ImageGenerationResult:
    image_bytes: bytes
    mime_type: str
    revised_prompt: str | None = None


class ImageProvider(ABC):
    name: str

    @abstractmethod
    async def generate(self, prompt: str, *, size: str | None = None) -> ImageGenerationResult:
        """Generate an image from a text prompt."""
