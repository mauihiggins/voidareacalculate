import unittest
import numpy as np
from PIL import Image, ImageDraw
from template_analysis import validate_pads, register, led_results

class TemplateTests(unittest.TestCase):
    def scene(self):
        rng=np.random.default_rng(4)
        image=Image.fromarray(np.uint8(np.clip(rng.normal(140,3,(400,400)),0,255)))
        d=ImageDraw.Draw(image)
        for _ in range(50):
            x,y=rng.integers(20,360,2);r=int(rng.integers(3,14));d.ellipse((x-r,y-r,x+r,y+r),fill=int(rng.integers(20,230)))
        d.rectangle((110,120,200,200),fill=45);d.ellipse((130,140,160,170),fill=95)
        pads=[dict(id='P1',led='LED7',polygon=[[110,120],[200,120],[200,200],[110,200]])]
        return image,pads

    def test_registration_translation_rotation_and_scale(self):
        image,pads=self.scene()
        theta=.10;scale=1.04;c,s=np.cos(theta),np.sin(theta)
        matrix=np.array([[c,-s],[s,c]])*scale;offset=np.array([200,200])+[9,-7]-matrix@np.array([200,200])
        inverse=np.linalg.inv(matrix)
        coefficients=tuple(np.c_[inverse,-inverse@offset].ravel())
        target=image.transform(image.size,Image.Transform.AFFINE,coefficients,Image.Resampling.BILINEAR,fillcolor=140)
        actual,quality=register(image,target,pads)
        expected=np.array(pads[0]['polygon'])@matrix.T+offset
        self.assertLess(np.max(np.linalg.norm(np.array(actual[0]['polygon'])-expected,axis=1)),2)
        self.assertGreater(quality['score'],.75)

    def test_wrong_product_rejected(self):
        image,pads=self.scene()
        with self.assertRaises(ValueError):register(image,Image.new('L',image.size,140),pads)

    def test_dynamic_pads_grouped_per_led(self):
        pads=[dict(id='P1',led='LED1',polygon=[[10,10],[40,10],[40,40],[10,40]],ratio=12),dict(id='P2',led='LED1',polygon=[[50,10],[90,10],[90,40],[50,40]],ratio=23),dict(id='P3',led='LED2',polygon=[[10,50],[60,50],[60,90],[10,90]],ratio=8)]
        validate_pads(pads,100,100)
        self.assertEqual(led_results(pads),{'LED1':23,'LED2':8})
        pads[1]['polygon']=pads[0]['polygon']
        with self.assertRaises(ValueError):validate_pads(pads,100,100)

    def test_self_intersection_rejected(self):
        with self.assertRaises(ValueError):validate_pads([dict(id='P1',led='LED1',polygon=[[0,0],[50,50],[0,50],[50,0]])],100,100)
