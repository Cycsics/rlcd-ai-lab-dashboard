from __future__ import annotations

from PIL import Image, ImageDraw

from pet import draw_pixel_pet


def test_pet_draws_black_pixels():
    image = Image.new("1", (120, 120), 255)
    draw = ImageDraw.Draw(image)
    draw_pixel_pet(draw, (10, 10, 110, 110), "idle", 0)
    pixels = image.load()
    black = sum(1 for y in range(120) for x in range(120) if pixels[x, y] == 0)
    assert black > 100

