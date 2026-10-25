from io import BytesIO
from pathlib import Path
from typing import Literal, TypeAlias

from PIL.Image import Image as _PILImage
from textual.widget import Widget

ProtocolName: TypeAlias = Literal["kitty", "sixel", "iterm2", "halfblock"]
ImageSource: TypeAlias = str | Path | _PILImage | BytesIO | None

class TerminalImage(Widget):
    def __init__(
        self,
        image: ImageSource = ...,
        *,
        name: str | None = ...,
        id: str | None = ...,
        classes: str | None = ...,
        disabled: bool = ...,
    ) -> None: ...
    @property
    def image(self) -> ImageSource: ...
    @image.setter
    def image(self, value: ImageSource) -> None: ...
    def force_protocol(self, name: ProtocolName) -> None: ...
    @property
    def protocol(self) -> str: ...
    @property
    def protocol_info(self) -> dict[str, object]: ...
