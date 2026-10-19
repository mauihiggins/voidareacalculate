import unittest
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from auto_analysis import analyze_auto, find_voids, measure, polygon_mask


class AutomaticAnalysisTests(unittest.TestCase):
    def test_blank_image_is_not_reported_as_four_pads(self):
        with self.assertRaisesRegex(ValueError,'대비'):
            analyze_auto(Image.new('L',(1032,1012),100))

    def test_overlapping_voids_count_once(self):
        pad=[(0,0),(100,0),(100,100),(0,100)]
        voids=[{'polygon':[(20,20),(40,20),(40,40),(20,40)]},
               {'polygon':[(30,30),(50,30),(50,50),(30,50)]}]
        result=measure(pad,voids,100,100)
        self.assertEqual(result['void_area'],700)
        self.assertEqual(result['ratio'],7)

    def test_closed_edges_find_voids_on_both_sides_of_copper(self):
        yy,xx=np.indices((160,240))
        truth=((xx-65)**2+(yy-80)**2<=23**2)|((xx-175)**2+(yy-80)**2<=23**2)
        gray=np.where(xx<120,100.,55.)+truth*18
        gray=gaussian_filter(gray,1.5)
        pad=[(15,15),(225,15),(225,145),(15,145)]
        voids=find_voids(gray,pad)
        mask=np.zeros_like(truth)
        for v in voids:mask|=polygon_mask(v['polygon'],(0,0,240,160))
        iou=(mask&truth).sum()/(mask|truth).sum()
        self.assertGreater(iou,.85)
        self.assertEqual(len(voids),2)

    def test_copper_band_without_voids(self):
        yy,xx=np.indices((160,240))
        gray=gaussian_filter(np.where(xx<120,100.,55.),1.5)
        self.assertEqual(find_voids(gray,[(15,15),(225,15),(225,145),(15,145)]),[])


if __name__=='__main__':
    unittest.main()
