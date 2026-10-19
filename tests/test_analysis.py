import unittest
import numpy as np
from PIL import Image
from void_analysis import analyze


class AnalysisTests(unittest.TestCase):
    def test_copper_shadow_and_crossing_void(self):
        yy, xx = np.indices((100, 140))
        background = np.where(xx < 70, 100, 55)
        truth = ((xx-35)**2+(yy-35)**2 <= 10**2) | ((xx-100)**2+(yy-35)**2 <= 10**2)
        truth |= (xx-70)**2+(yy-70)**2 <= 12**2
        im = Image.fromarray((background + truth*20).astype('uint8'))
        polygon = [(0,0),(140,0),(140,100),(0,100)]
        absolute = analyze(im, polygon, 110, 1)
        local = analyze(im, polygon, minimum=1, mode='local', contrast_threshold=10, background_radius=16)
        self.assertLess(absolute['void_area'], int(truth.sum()))
        np.testing.assert_array_equal(local['mask'], truth)

    def test_shadow_without_void_and_outside_brightness(self):
        yy, xx = np.indices((100,140))
        background = np.where(xx < 70, 100, 55).astype('uint8')
        polygon = [(10,10),(130,10),(130,90),(10,90)]
        for outside in (0,255):
            a = background.copy()
            a[:10] = a[90:] = outside
            a[:,:10] = a[:,130:] = outside
            r = analyze(Image.fromarray(a),polygon,minimum=1,mode='local',contrast_threshold=8,background_radius=16)
            self.assertEqual(r['void_area'],0)

    def test_local_additive_brightness_invariance(self):
        a = np.full((80,80),60,dtype='uint8')
        a[25:45,25:45] = 80
        polygon = [(5,5),(75,5),(75,75),(5,75)]
        first = analyze(Image.fromarray(a),polygon,mode='local',background_radius=15)
        second = analyze(Image.fromarray(a+40),polygon,mode='local',background_radius=15)
        np.testing.assert_array_equal(first['mask'],second['mask'])
        self.assertEqual(first['void_area'],400)

    def test_known_ratio_and_outside_exclusion(self):
        a = np.zeros((12, 12), dtype=np.uint8)
        a[2:5, 2:7] = 200
        a[10:, :] = 255
        r = analyze(Image.fromarray(a), [(0,0),(10,0),(10,10),(0,10)], 125, 1)
        self.assertEqual((r['pad_area'], r['void_area'], r['ratio']), (100, 15, 15))
        self.assertEqual(r['sizes'], [15])

    def test_filter_and_diagonal_connectivity(self):
        a = np.zeros((10,10), dtype=np.uint8)
        a[1,1] = a[2,2] = a[8,8] = 180
        r = analyze(Image.fromarray(a), [(0,0),(10,0),(10,10),(0,10)], 180, 2)
        self.assertEqual(r['sizes'], [2])
        self.assertEqual(int(r['mask'].sum()), 2)

    def test_triangle_pixel_centers(self):
        r = analyze(Image.new('L',(4,4),255), [(0,0),(4,0),(0,4)], 100, 1)
        self.assertEqual(r['pad_area'], 6)
        self.assertEqual(r['ratio'],100)

    def test_empty_detection(self):
        r = analyze(Image.new('L',(4,4)), [(0,0),(4,0),(4,4),(0,4)], 1, 1)
        self.assertEqual(r['ratio'],0)

    def test_degenerate_polygon(self):
        with self.assertRaises(ValueError):
            analyze(Image.new('L',(4,4)), [(0,0),(1,1),(2,2)])


if __name__ == '__main__':
    unittest.main()
