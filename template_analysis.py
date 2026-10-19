"""User-defined pads, conservative similarity registration, and void measurement."""
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.optimize import differential_evolution
from auto_analysis import find_voids, measure, polygon_mask


def correlation(a, b):
    a=a-a.mean(); b=b-b.mean()
    return float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-9))


def validate_pads(pads, width, height):
    if not 1 <= len(pads) <= 64:
        raise ValueError('패드는 1~64개 등록하세요.')
    ids=set()
    for pad in pads:
        if not pad['id'] or pad['id'] in ids or not pad['led'].strip():
            raise ValueError('패드 번호는 고유해야 하며 LED 번호가 필요합니다.')
        ids.add(pad['id'])
        p=np.asarray(pad['polygon'],float)
        if p.ndim!=2 or p.shape[1]!=2 or not 3<=len(p)<=256 or not np.isfinite(p).all():
            raise ValueError('올바른 패드 다각형이 필요합니다.')
        if (p<0).any() or (p[:,0]>width).any() or (p[:,1]>height).any():
            raise ValueError('패드 경계가 이미지 밖에 있습니다.')
        # Reject self intersections rather than giving ambiguous measured areas.
        def cross(a,b,c):
            u,v=b-a,c-a
            return u[0]*v[1]-u[1]*v[0]
        for i in range(len(p)):
            a,b=p[i],p[(i+1)%len(p)]
            if np.linalg.norm(a-b)<.01: raise ValueError('중복 꼭짓점을 제거하세요.')
            for j in range(i+2,len(p)):
                if i==0 and j==len(p)-1: continue
                c,d=p[j],p[(j+1)%len(p)]
                if cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0:
                    raise ValueError('패드 경계가 교차합니다. 둘레 순서로 지정하세요.')
        if measure(p,[],width,height)['pad_area']<25:
            raise ValueError('패드 면적이 너무 작습니다.')
    for i,a in enumerate(pads):
        for b in pads[i+1:]:
            p=np.asarray(a['polygon']+b['polygon'])
            box=(*np.floor(p.min(axis=0)).astype(int),*np.ceil(p.max(axis=0)).astype(int))
            if (polygon_mask(a['polygon'],box)&polygon_mask(b['polygon'],box)).any():
                raise ValueError('패드 경계가 서로 겹칩니다.')


def register(reference, image, pads):
    """Estimate uniform scale/rotation/translation; reject poor or cropped matches."""
    rw,rh=reference.size; w,h=image.size
    if abs((w/h)/(rw/rh)-1)>.08:
        raise ValueError('기준 사진과 가로세로 비율이 다릅니다. 같은 촬영 구도로 등록하세요.')
    n=256; nh=round(n*rh/rw)
    a=np.asarray(reference.convert('L').resize((n,nh)),float)
    b=np.asarray(image.convert('L').resize((n,nh)),float)
    a=gaussian_filter(a,1);b=gaussian_filter(b,1)
    a=a-gaussian_filter(a,8);b=b-gaussian_filter(b,8)
    yy,xx=np.mgrid[8:nh-8:3,8:n-8:3]
    coords=np.c_[xx.ravel(),yy.ravel()]; center=np.array([n/2,nh/2])
    values=a[yy,xx].ravel()
    if values.std()<.5: raise ValueError('기준 영상의 대비가 부족합니다.')
    def transform(points,params):
        angle,scale,tx,ty=params;c,s=np.cos(angle),np.sin(angle)
        return (points-center)@np.array([[c,s],[-s,c]])*scale+center+[tx,ty]
    def score(params):
        q=transform(coords,params)
        valid=(q[:,0]>=0)&(q[:,0]<n-1)&(q[:,1]>=0)&(q[:,1]<nh-1)
        if valid.mean()<.8:return 1
        v=map_coordinates(b,q[valid].T[::-1],order=1)
        return -correlation(values[valid],v)
    identity=[0,1,0,0]
    if score(identity)<-.995: params=identity
    else:
        fit=differential_evolution(score,[(-.35,.35),(.85,1.15),(-n*.15,n*.15),(-nh*.15,nh*.15)],seed=29,popsize=8,maxiter=75,tol=.002,polish=True)
        params=fit.x
    quality=-score(params)
    if quality<.75: raise ValueError('기준 사진과 정렬이 맞지 않습니다. 해당 제품 설정인지 확인하거나 새 기준으로 등록하세요.')
    result=[]
    for pad in pads:
        p=np.asarray(pad['polygon'])*[n/rw,nh/rh]
        q=transform(p,params)*[w/n,h/nh]
        if (q<0).any() or (q[:,0]>w).any() or (q[:,1]>h).any():
            raise ValueError('정렬된 패드가 사진 밖으로 잘렸습니다.')
        # Check each pad neighborhood so a shared board background alone is insufficient.
        low=np.maximum(0,np.floor(p.min(axis=0)-5)).astype(int)
        high=np.minimum([n,nh],np.ceil(p.max(axis=0)+5)).astype(int)
        y,x=np.mgrid[low[1]:high[1],low[0]:high[0]]
        pc=np.c_[x.ravel(),y.ravel()];qc=transform(pc,params)
        v=map_coordinates(b,qc.T[::-1],order=1,mode='nearest')
        if correlation(a[y,x].ravel(),v)<.5:
            raise ValueError(f"{pad['id']} 주변이 기준과 다릅니다. 패드 위치를 확인하고 다시 등록하세요.")
        result.append(dict(id=pad['id'],led=pad['led'],polygon=q.tolist()))
    return result,dict(score=round(quality,4),rotation_degrees=round(float(params[0])*180/np.pi,3),scale=round(float(params[1]),5))


def led_results(pads):
    return {led:max(p['ratio'] for p in pads if p.get('led')==led) for led in sorted({p['led'] for p in pads if p.get('led')})}


def analyze_template(image, reference, template, sensitivity=1):
    pads,alignment=register(reference,image,template['pads'])
    w,h=image.size;scale=min(1,1032/w)
    gray=np.asarray(image.convert('L').resize((round(w*scale),round(h*scale))),float)
    for pad in pads:
        voids=find_voids(gray,(np.asarray(pad['polygon'])*scale).tolist(),sensitivity)
        pad['voids']=[dict(polygon=(np.asarray(v['polygon'])/scale).tolist(),support=v['support']) for v in voids]
        pad.update(measure(pad['polygon'],pad['voids'],w,h))
        pad['warning']='검출된 보이드가 없습니다. 원본을 확인하세요.' if not voids else ''
    return dict(width=w,height=h,pads=pads,method='registered-template-v1',template_id=template['id'],template_name=template['name'],alignment=alignment,led_results=led_results(pads),sensitivity=sensitivity,edited=False,estimate=True)
