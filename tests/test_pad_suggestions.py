import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageDraw
from auto_analysis import suggest_pads
from template_analysis import validate_pads


class PadSuggestionTests(unittest.TestCase):
    def test_legacy_layout_can_be_saved_as_template(self):
        image = Image.new('L', (1032, 1012), 180)
        draw = ImageDraw.Draw(image)
        for x, y in [(365, 380), (715, 380), (365, 660), (715, 660)]:
            draw.rounded_rectangle((x-135, y-100, x+135, y+100), radius=30, fill=65)
        pads = suggest_pads(image)
        self.assertEqual(len(pads), 4)
        validate_pads([dict(p, led='LED1') for p in pads], *image.size)
        for pad, center in zip(pads, [(365,380),(715,380),(365,660),(715,660)]):
            self.assertLess(np.linalg.norm(np.mean(pad['polygon'], axis=0)-center), 15)

    def test_original_image_coordinates(self):
        image = Image.fromarray(np.tile(np.arange(516, dtype=np.uint8), (506,1)))
        with patch('auto_analysis.find_pads', return_value=[{'id':'P1','polygon':[[100,100],[300,100],[300,300]]}]):
            self.assertEqual(suggest_pads(image)[0]['polygon'], [[50,50],[150,50],[150,150]])

    def test_blank_and_wrong_shape_rejected(self):
        for size in [(1032,1012),(100,100),(1200,300)]:
            with self.assertRaises(ValueError):
                suggest_pads(Image.new('L', size, 128))
