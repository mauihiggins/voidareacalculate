"""Automatic 4-pad X-ray analysis. Results are image-based area estimates."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter, maximum_filter, map_coordinates, median_filter
from scipy.optimize import differential_evolution
from scipy.signal import fftconvolve


def polygon_mask(polygon, box):
    x0, y0, x1, y1 = box
    yy, xx = np.mgrid[y0:y1, x0:x1]
    xx = xx + .5
    yy = yy + .5
    hit = np.zeros(xx.shape, dtype=bool)
    points = list(polygon)
    for a, b in zip(points, points[1:]+points[:1]):
        if a[1] == b[1]:
            continue
        hit ^= ((a[1] > yy) != (b[1] > yy)) & (xx < (b[0]-a[0])*(yy-a[1])/(b[1]-a[1])+a[0])
    return hit


def rounded_polygon(parameters):
    cx, cy, w, h, angle = parameters
    w -= 10
    h -= 10
    radius = min(38, h/4, w/4)
    points = []
    for x, y, begin in [(w/2-radius,h/2-radius,0),(-w/2+radius,h/2-radius,90),
                        (-w/2+radius,-h/2+radius,180),(w/2-radius,-h/2+radius,270)]:
        theta = np.linspace(begin, begin+90, 20, endpoint=False)*np.pi/180
        points.extend(np.c_[x+radius*np.cos(theta), y+radius*np.sin(theta)])
    c, s = np.cos(angle), np.sin(angle)
    return np.array(points) @ np.array([[c,s],[-s,c]]) + [cx,cy]


def edge_samples(parameters):
    cx, cy, w, h, angle = parameters
    t = np.linspace(-.75, .75, 22)
    points = np.vstack([np.c_[t*w/2,np.full_like(t,-h/2)],
                        np.c_[np.full_like(t,w/2),t*h/2],
                        np.c_[t*w/2,np.full_like(t,h/2)],
                        np.c_[np.full_like(t,-w/2),t*h/2]])
    normals = np.repeat([[0,-1],[1,0],[0,1],[-1,0]], len(t), axis=0)
    c,s = np.cos(angle),np.sin(angle)
    rotation = np.array([[c,-s],[s,c]])
    return points@rotation.T+[cx,cy], normals@rotation.T


def find_pads(gray):
    height, width = gray.shape
    sy, sx = height/1012, width/1032
    smooth = gaussian_filter(gray, 2)
    pads = []
    for index in range(4):
        right, bottom = index%2, index//2
        bounds = [tuple(v*sx for v in ((610,820) if right else (270,460))),
                  tuple(v*sy for v in ((565,750) if bottom else (290,470))),
                  (235*sx,300*sx),(170*sy,230*sy),(-.26,.26)]
        def loss(parameters):
            points,normals = edge_samples(parameters)
            outside = map_coordinates(smooth, (points+normals*8).T[::-1], order=1)
            inside = map_coordinates(smooth, (points-normals*8).T[::-1], order=1)
            means = np.clip(outside-inside,-30,45).reshape(4,-1).mean(axis=1)
            return -(.7*means.mean()+.3*means.min())
        fit = differential_evolution(loss,bounds,popsize=7,maxiter=65,tol=.008,seed=17,polish=True)
        if -fit.fun < 2.0:
            raise ValueError('4개 패드 경계를 확인하기 어렵습니다. 제공된 샘플처럼 패드 4개가 중앙에 보이는 원본을 사용하세요.')
        polygon = rounded_polygon(fit.x)
        pads.append({'id':f'P{index+1}','polygon':polygon.tolist(),'edge_score':round(-fit.fun,2)})
    return pads


def find_voids(gray, polygon, sensitivity=1.0):
    """Closed bright boundaries reject long copper bands; dark interiors are allowed."""
    points=np.array(polygon)
    x0,y0=np.maximum(0,np.floor(points.min(axis=0)-2)).astype(int)
    x1,y1=np.minimum([gray.shape[1],gray.shape[0]],np.ceil(points.max(axis=0)+3)).astype(int)
    region=polygon_mask(polygon,(x0,y0,x1,y1))
    smooth=gaussian_filter(gray,1)
    rx,ry=max(0,x0-80),max(0,y0-80)
    roi=smooth[ry:min(gray.shape[0],y1+80),rx:min(gray.shape[1],x1+80)]
    radii=np.array([7,10,13,16,20,25,30,36,43,50,58,66],float)
    responses=[]
    for r in radii:
        n=int(r+7)
        yy,xx=np.mgrid[-n:n+1,-n:n+1]
        distance=np.hypot(xx,yy)
        inside=(distance>=r-4)&(distance<r-1)
        outside=(distance>=r+1)&(distance<r+4)
        kernel=inside/inside.sum()-outside/outside.sum()
        responses.append(fftconvolve(roi,kernel,mode='same'))
    responses=np.stack(responses)
    peaks=(responses==maximum_filter(responses,size=(3,9,9)))&(responses>1.25/sensitivity)
    candidates=[]
    for si,cy,cx in np.array(np.nonzero(peaks)).T:
        score=float(responses[si,cy,cx]);cx+=rx;cy+=ry;r=radii[si]
        if not(y0<=cy<y1 and x0<=cx<x1 and region[cy-y0,cx-x0]):
            continue
        theta=np.arange(64)*2*np.pi/64
        px=np.rint(cx+np.cos(theta)*r).astype(int)-x0
        py=np.rint(cy+np.sin(theta)*r).astype(int)-y0
        valid=(px>=0)&(px<x1-x0)&(py>=0)&(py<y1-y0)
        inside=np.zeros(64,bool);inside[valid]=region[py[valid],px[valid]]
        if inside.mean()<.9:
            continue
        samples=np.linspace(max(3,r*.8),r*1.2,24)
        xx=cx+np.cos(theta[:,None])*samples
        yy=cy+np.sin(theta[:,None])*samples
        step=max(2.5,r*.06)
        gradient=(map_coordinates(smooth,[yy-np.sin(theta[:,None])*step,xx-np.cos(theta[:,None])*step],order=1)
                  - map_coordinates(smooth,[yy+np.sin(theta[:,None])*step,xx+np.cos(theta[:,None])*step],order=1))
        weighted=gradient*np.exp(-.5*((samples/r-1)/.12)**2)
        best=weighted.argmax(axis=1)
        strength=gradient[np.arange(64),best]
        supported=strength>max(.65/sensitivity,score*.18)
        if supported.mean()<.60:
            continue
        contour=np.where(supported,samples[best],r)
        contour=median_filter(np.tile(contour,3),size=11)[64:128]
        if r<10 and (score<2.2/sensitivity or supported.mean()<.75):
            continue
        candidates.append(dict(cx=int(cx),cy=int(cy),radius=float(r),score=score,
                               support=float(supported.mean()),
                               polygon=np.c_[cx+np.cos(theta)*contour,cy+np.sin(theta)*contour].tolist()))
    candidates.sort(key=lambda b:b['score']*b['radius'],reverse=True)
    kept=[]
    for candidate in candidates:
        if any(np.hypot(candidate['cx']-other['cx'],candidate['cy']-other['cy']) <
               max(candidate['radius'],other['radius'])+.6*min(candidate['radius'],other['radius']) for other in kept):
            continue
        kept.append(candidate)
    return kept


def measure(polygon, voids, width, height):
    points=np.array(polygon)
    x0,y0=np.maximum(0,np.floor(points.min(axis=0))).astype(int)
    x1,y1=np.minimum([width,height],np.ceil(points.max(axis=0)+1)).astype(int)
    if x1<=x0 or y1<=y0:
        raise ValueError('패드 영역이 이미지 밖에 있습니다.')
    box=(x0,y0,x1,y1)
    region=polygon_mask(polygon,box)
    mask=np.zeros_like(region)
    for void in voids:
        mask |= polygon_mask(void['polygon'],box)
    mask &= region
    area=int(region.sum())
    if not area:
        raise ValueError('패드 면적이 없습니다.')
    void_area=int(mask.sum())
    return {'pad_area':area,'void_area':void_area,'ratio':100*void_area/area,'count':len(voids)}


def analyze_auto(image, sensitivity=1.0):
    if not .5<=sensitivity<=2:
        raise ValueError('민감도는 0.5~2 범위여야 합니다.')
    width,height=image.size
    if min(width,height)<300 or not .65<=width/height<=1.5:
        raise ValueError('샘플과 같은 4패드 촬영 구도의 가로·세로 300px 이상 이미지를 사용하세요.')
    scale=1032/width
    small=image.convert('L').resize((1032,round(height*scale)),Image.Resampling.LANCZOS)
    gray=np.asarray(small,dtype=float)
    if float(np.std(gray))<2:
        raise ValueError('영상 대비가 부족하여 패드 경계를 찾을 수 없습니다.')
    pads=find_pads(gray)
    for pad in pads:
        voids=find_voids(gray,pad['polygon'],sensitivity)
        pad['polygon']=(np.array(pad['polygon'])/scale).round(3).tolist()
        for void in voids:
            void['polygon']=(np.array(void['polygon'])/scale).round(3).tolist()
        pad['voids']=[{'polygon':v['polygon'],'support':round(v['support'],3)} for v in voids]
        pad.update(measure(pad['polygon'],pad['voids'],width,height))
        pad['warning']='검출된 보이드가 없습니다. 원본을 확인하세요.' if not voids else ''
    return {'width':width,'height':height,'pads':pads,'method':'closed-boundary-v1',
            'sensitivity':sensitivity,'edited':False,'estimate':True}


def render_result(image, result):
    """Render a quantitative image-analysis overlay, clipping fills to pad boundaries."""
    output=image.convert('RGB').copy()
    pixels=np.array(output)
    for pad in result['pads']:
        points=np.array(pad['polygon'])
        x0,y0=np.maximum(0,np.floor(points.min(axis=0))).astype(int)
        x1,y1=np.minimum(output.size,np.ceil(points.max(axis=0)+1)).astype(int)
        box=(x0,y0,x1,y1)
        region=polygon_mask(pad['polygon'],box)
        mask=np.zeros_like(region)
        for void in pad['voids']:
            mask|=polygon_mask(void['polygon'],box)
        pixels[y0:y1,x0:x1][mask&region]=[0,255,40]
    output=Image.fromarray(pixels)
    draw=ImageDraw.Draw(output)
    size=max(14,round(image.width/34))
    try:
        font=ImageFont.truetype('DejaVuSans-Bold.ttf',size)
    except OSError:
        font=ImageFont.load_default(size=size)
    for pad in result['pads']:
        polygon=[tuple(p) for p in pad['polygon']]
        draw.line(polygon+[polygon[0]],fill=(0,255,40),width=max(1,size//12))
        label=f"{pad['id']} {pad['ratio']:.1f}%"
        center=np.mean(np.array(polygon),axis=0)
        x=max(0,min(image.width-200,int(center[0]-100)))
        y=min(image.height-size-12,int(max(p[1] for p in polygon)+10))
        box=draw.textbbox((x,y),label,font=font)
        draw.rectangle((box[0]-4,box[1]-3,box[2]+4,box[3]+3),fill='black')
        draw.text((x,y),label,font=font,fill=(0,255,40))
    draw.text((12,12),'IMAGE-BASED AREA ESTIMATE',font=font,fill=(255,222,120),stroke_width=1,stroke_fill='black')
    return output
