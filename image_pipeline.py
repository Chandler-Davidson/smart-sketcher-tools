from __future__ import annotations

from io import BytesIO
from typing import Iterable

from PIL import Image

TARGET_WIDTH = 160
TARGET_HEIGHT = 128


class ImageValidationError(Exception):
    pass


def _load_image(image_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(image_bytes))
        image.load()
        return image
    except Exception as exc:
        raise ImageValidationError("Could not decode image data") from exc


def prepare_image_from_bytes(
    image_bytes: bytes,
    fit_mode: str = "contain",
    background_rgb: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    image = _load_image(image_bytes)
    return prepare_image(image, fit_mode=fit_mode, background_rgb=background_rgb)


def prepare_image_from_path(
    image_path: str,
    fit_mode: str = "contain",
    background_rgb: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    try:
        image = Image.open(image_path)
        image.load()
    except Exception as exc:
        raise ImageValidationError(f"Could not open image file: {image_path}") from exc

    return prepare_image(image, fit_mode=fit_mode, background_rgb=background_rgb)


def prepare_image(
    image: Image.Image,
    fit_mode: str = "contain",
    background_rgb: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    image = image.convert("RGB")

    if fit_mode not in {"contain", "stretch"}:
        raise ImageValidationError("fit_mode must be 'contain' or 'stretch'")

    if fit_mode == "stretch":
        return image.resize((TARGET_WIDTH, TARGET_HEIGHT))

    ratio = min(TARGET_WIDTH / image.width, TARGET_HEIGHT / image.height)
    resized_width = max(1, int(image.width * ratio))
    resized_height = max(1, int(image.height * ratio))
    resized = image.resize((resized_width, resized_height))

    canvas = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), background_rgb)
    offset_x = (TARGET_WIDTH - resized_width) // 2
    offset_y = (TARGET_HEIGHT - resized_height) // 2
    canvas.paste(resized, (offset_x, offset_y))
    return canvas


def image_to_rgb565_lines(image: Image.Image) -> list[bytearray]:
    if image.mode != "RGB":
        image = image.convert("RGB")

    if image.width != TARGET_WIDTH or image.height != TARGET_HEIGHT:
        raise ImageValidationError(
            f"Image must be {TARGET_WIDTH}x{TARGET_HEIGHT} before RGB565 conversion"
        )

    lines: list[bytearray] = []

    for y in range(TARGET_HEIGHT):
        line_data = bytearray()
        for x in range(TARGET_WIDTH):
            r, g, b = image.getpixel((x, y))
            byte1 = (r & 0xF8) | (g >> 5)
            byte2 = ((g & 0x1C) << 3) | (b >> 3)
            line_data.append(byte1)
            line_data.append(byte2)

        lines.append(line_data)

    return lines


def image_bytes_to_rgb565_lines(image_bytes: bytes, fit_mode: str = "contain") -> list[bytearray]:
    prepared = prepare_image_from_bytes(image_bytes, fit_mode=fit_mode)
    return image_to_rgb565_lines(prepared)


def image_path_to_rgb565_lines(image_path: str, fit_mode: str = "contain") -> list[bytearray]:
    prepared = prepare_image_from_path(image_path, fit_mode=fit_mode)
    return image_to_rgb565_lines(prepared)
