"""Local web service for automatic X-ray inspection; no external image services."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, StringIO
from pathlib import Path
from threading import RLock
from uuid import uuid4
from zipfile import ZipFile, BadZipFile
import csv
import json
import os
import time

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from auto_analysis import measure, render_result
from template_analysis import analyze_template, validate_pads, led_results

ROOT=Path(__file__).parent
DATA=ROOT/'.runtime'
DATA.mkdir(exist_ok=True)
TEMPLATES=DATA/'templates'
TEMPLATES.mkdir(exist_ok=True)

def get_template(key):
    if not key or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):
        raise HTTPException(400,'검사 설정을 선택하세요.')
    path=TEMPLATES/(key+'.json')
    if not path.exists(): raise HTTPException(404,'검사 설정을 찾을 수 없습니다.')
    return json.loads(path.read_text(encoding='utf-8'))
app=FastAPI(title='Void Inspect')
pool=ThreadPoolExecutor(max_workers=2)
lock=RLock()
jobs={}
MAX_UPLOAD=32*1024*1024
EXTENSIONS={'.jpg','.jpeg','.png','.bmp','.tif','.tiff','.webp'}


def public(job, full=False):
    keys=['id','name','status','kind','error','created','template_id']
    data={key:job.get(key) for key in keys}
    result=job.get('result')
    data['max_ratio']=max((p['ratio'] for p in result['pads']),default=0) if result else None
    data['pad_count']=len(result['pads']) if result else 0
    if full:
        data['result']=result
    return data


def save(job):
    if job['kind']=='reviewed':
        return
    path=DATA/(job['id']+'.json')
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8')
    temp.replace(path)


def get_job(key):
    with lock:
        if key not in jobs:
            raise HTTPException(404,'이미지를 찾을 수 없습니다.')
        return jobs[key]


def run_analysis(key,sensitivity=1.0):
    with lock:
        job=jobs[key]
        job['status']='running'
        job['error']=None
    try:
        template=get_template(job.get('template_id'))
        with Image.open(job['_image_path']) as image, Image.open(TEMPLATES/(template['id']+'.png')) as reference:
            result=analyze_template(image,reference,template,sensitivity)
        with lock:
            job['result']=result
            job['status']='done'
            save(job)
    except Exception as error:
        with lock:
            job['status']='error'
            job['error']=str(error)
            job['result']=None
            save(job)


def add_image(name,raw,template_id=None):
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.width*source.height>20_000_000:
                raise ValueError('이미지는 2천만 픽셀 이하로 업로드하세요.')
            image=ImageOps.exif_transpose(source).convert('RGB')
            image.load()
    except (UnidentifiedImageError,OSError,ValueError) as error:
        raise ValueError(f'{name}: 이미지를 읽을 수 없습니다. {error}') from error
    key=uuid4().hex
    path=DATA/(key+'.png')
    image.save(path)
    job=dict(id=key,name=name,status='queued' if template_id else 'needs_template',kind='auto',created=time.time(),
             error=None,result=None,_image_path=str(path),template_id=template_id)
    with lock:
        jobs[key]=job
        save(job)
    if template_id: pool.submit(run_analysis,key)
    return key


def load_samples():
    manifest=Path(os.environ.get('VOID_SAMPLE_MANIFEST','/workspace/customer_report/work/interpreted_analysis.json'))
    if not manifest.exists():
        return
    for record in json.loads(manifest.read_text()):
        path=manifest.parent/record['file']
        if not path.is_file():
            continue
        key=f"sample-{record['slide']:02d}-{record['picture']}"
        with Image.open(path) as image:
            width,height=image.size
        pads=[]
        for index,p in enumerate(record['pads']):
            pads.append(dict(id=f'P{index+1}',polygon=p['polygon'],
                             voids=[dict(polygon=b['polygon'],support=b.get('support',0)) for b in p['blobs']],
                             pad_area=p['pad_area'],void_area=p['void_area'],ratio=p['ratio'],
                             count=len(p['blobs']),warning=''))
        parts=Path(record['source']).parts
        name=f'{parts[-4]} / {parts[-2].rstrip("_")} / LD{Path(parts[-1]).stem}'
        jobs[key]=dict(id=key,name=name,status='done',kind='reviewed',created=0,error=None,
                       _image_path=str(path),result=dict(width=width,height=height,pads=pads,
                        method='visually-reviewed-report',sensitivity=1.0,edited=False,estimate=True))


load_samples()
for path in DATA.glob('*.json'):
    try:
        job=json.loads(path.read_text())
        if job['id']+'.json'!=path.name or not (DATA/(job['id']+'.png')).exists():
            continue
        job['_image_path']=str(DATA/(job['id']+'.png'))
        if job['status'] in ('queued','running'):
            job['status']='error';job['error']='서버 재시작으로 분석이 중단되었습니다. 다시 분석하세요.'
        jobs[job['id']]=job
    except (ValueError,KeyError,OSError):
        continue


@app.get('/api/dev/version')
def development_version():
    if os.environ.get('VOID_DEV_RELOAD')!='1':
        return {'enabled':False}
    import hashlib
    paths=sorted(ROOT.glob('*.py'))+sorted((ROOT/'web').glob('*'))
    digest=hashlib.sha256()
    for path in paths:
        if path.is_file():
            digest.update(path.name.encode());digest.update(path.read_bytes())
    return {'enabled':True,'version':digest.hexdigest()}

@app.middleware('http')
async def development_cache(request:Request,call_next):
    response=await call_next(request)
    if os.environ.get('VOID_DEV_RELOAD')=='1':
        response.headers['Cache-Control']='no-store'
    return response


@app.get('/api/health')
def health():
    return {'status':'ok','profile':'registered-pads','samples':sum(j['kind']=='reviewed' for j in jobs.values())}


@app.get('/api/jobs')
def list_jobs():
    with lock:
        return [public(job) for job in jobs.values()]


@app.get('/api/jobs/{key}')
def detail(key:str):
    with lock:
        return public(get_job(key),True)


@app.get('/api/jobs/{key}/image')
def image(key:str):
    return FileResponse(get_job(key)['_image_path'])


@app.post('/api/import')
async def import_images(request:Request,name:str='image.png',template_id:str|None=None):
    if template_id: get_template(template_id)
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>MAX_UPLOAD:
            raise HTTPException(413,'파일당 최대 32 MB입니다.')
        chunks.append(chunk)
    raw=b''.join(chunks)
    with lock:
        if sum(j['status'] in ('queued','running') for j in jobs.values())>=200:
            raise HTTPException(429,'분석 대기열이 가득 찼습니다. 완료 후 다시 업로드하세요.')
    accepted=[];errors=[]
    if Path(name).suffix.lower()=='.zip':
        try:
            with ZipFile(BytesIO(raw)) as archive:
                entries=[e for e in archive.infolist() if not e.is_dir() and Path(e.filename).suffix.lower() in EXTENSIONS]
                if not entries:
                    raise HTTPException(400,'ZIP에 지원하는 이미지가 없습니다.')
                if len(entries)>100 or sum(e.file_size for e in entries)>100*1024*1024:
                    raise HTTPException(413,'ZIP은 이미지 100장, 압축 해제 기준 100 MB 이하를 사용하세요.')
                for entry in entries:
                    if entry.file_size>MAX_UPLOAD:
                        errors.append(f'{entry.filename}: 이미지 파일이 너무 큽니다.');continue
                    try:
                        accepted.append(add_image(entry.filename,archive.read(entry),template_id))
                    except (ValueError,RuntimeError,Image.DecompressionBombError) as error:
                        errors.append(str(error))
        except BadZipFile:
            raise HTTPException(400,'ZIP 파일을 읽을 수 없습니다.')
    else:
        try:
            accepted.append(add_image(name,raw,template_id))
        except (ValueError,Image.DecompressionBombError) as error:
            raise HTTPException(400,str(error))
    return {'ids':accepted,'errors':errors}


class AnalyzeRequest(BaseModel):
    template_id:str
    sensitivity:float=Field(default=1,ge=.5,le=2)


@app.post('/api/jobs/{key}/analyze')
def reanalyze(key:str,options:AnalyzeRequest):
    original=get_job(key)
    get_template(options.template_id)
    with lock:
        if original['status'] in ('running','queued'):
            raise HTTPException(409,'이미 분석 중입니다.')
    # Preserve reviewed reports and previous results; a rerun is a separate record.
    with Image.open(original['_image_path']) as image:
        buffer=BytesIO();image.save(buffer,format='PNG')
    new_key=uuid4().hex;path=DATA/(new_key+'.png');path.write_bytes(buffer.getvalue())
    job=dict(id=new_key,name=original['name']+' · 재분석',status='queued',kind='auto',
             created=time.time(),error=None,result=None,_image_path=str(path),template_id=options.template_id)
    with lock:
        jobs[new_key]=job;save(job)
    pool.submit(run_analysis,new_key,options.sensitivity)
    return {'id':new_key}


class VoidShape(BaseModel):
    polygon:list[tuple[float,float]]=Field(min_length=3,max_length=256)


class PadEdit(BaseModel):
    id:str
    voids:list[VoidShape]=Field(max_length=300)


class EditRequest(BaseModel):
    pads:list[PadEdit]=Field(min_length=1,max_length=64)


@app.post('/api/jobs/{key}/edits')
def edits(key:str,body:EditRequest):
    import math
    with lock:
        job=get_job(key)
        if job['status']!='done':
            raise HTTPException(409,'분석 완료 후 수정할 수 있습니다.')
        result=json.loads(json.dumps(job['result']))
        if [p.id for p in body.pads]!=[p['id'] for p in result['pads']]:
            raise HTTPException(400,'패드 순서가 일치하지 않습니다.')
        for change,pad in zip(body.pads,result['pads']):
            for void in change.voids:
                if any(not(math.isfinite(x) and math.isfinite(y) and 0<=x<=result['width'] and 0<=y<=result['height']) for x,y in void.polygon):
                    raise HTTPException(400,'보이드 좌표가 이미지 범위를 벗어났습니다.')
            pad['voids']=[v.model_dump() for v in change.voids]
            pad.update(measure(pad['polygon'],pad['voids'],result['width'],result['height']))
        result['edited']=True
        result['led_results']=led_results(result['pads'])
        # Report samples are kept immutable on disk; edited copies persist independently.
        if job['kind']=='reviewed':
            new_key=uuid4().hex
            path=DATA/(new_key+'.png')
            with Image.open(job['_image_path']) as image:
                image.save(path)
            job=dict(job,id=new_key,name=job['name']+' · 수정',kind='edited',_image_path=str(path),created=time.time(),result=result)
            jobs[new_key]=job
        else:
            job['kind']='edited'
            job['result']=result
        save(job)
        return public(job,True)


@app.get('/api/jobs/{key}/export.png')
def export_image(key:str):
    job=get_job(key)
    if job['status']!='done':
        raise HTTPException(409,'분석 결과가 없습니다.')
    with Image.open(job['_image_path']) as source:
        result=render_result(source,job['result'])
    buffer=BytesIO();result.save(buffer,format='PNG')
    return Response(buffer.getvalue(),media_type='image/png',headers={'Content-Disposition':f'attachment; filename="void-{key}.png"'})


@app.get('/api/export.csv')
def export_csv():
    buffer=StringIO();writer=csv.writer(buffer)
    writer.writerow(['image','source','pad','led','led_max_ratio_percent','pad_area_px','void_area_px','estimated_ratio_percent','void_count'])
    with lock:
        for job in jobs.values():
            if job['status']!='done':continue
            for pad in job['result']['pads']:
                name=job['name']
                if name[:1] in ('=','+','-','@'):name="'"+name
                writer.writerow([name,job['kind'],pad['id'],("'"+pad.get('led','') if pad.get('led','')[:1] in ('=','+','-','@') else pad.get('led','')),round(job['result'].get('led_results',{}).get(pad.get('led'),0),2) if pad.get('led') else '',pad['pad_area'],pad['void_area'],round(pad['ratio'],2),pad['count']])
    return Response('\ufeff'+buffer.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="void-results.csv"'})


@app.get('/api/reports/{kind}')
def report(kind:str):
    names={'pptx':'XRay_void_area_annotated.pptx','pdf':'XRay_void_area_annotated.pdf','zip':'annotated_photos_and_results.zip'}
    if kind not in names:raise HTTPException(404)
    path=Path('/workspace/artifacts/void-analysis')/names[kind]
    if not path.is_file():raise HTTPException(404,'고객 자료 파일이 이 환경에 없습니다.')
    return FileResponse(path,filename=path.name)



class TemplatePad(BaseModel):
    id:str=Field(min_length=1,max_length=30)
    led:str=Field(min_length=1,max_length=40)
    polygon:list[tuple[float,float]]=Field(min_length=3,max_length=256)

class TemplateRequest(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    job_id:str
    pads:list[TemplatePad]=Field(min_length=1,max_length=64)

@app.get('/api/templates')
def templates():
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted(TEMPLATES.glob('*.json'))]

@app.post('/api/templates')
def create_template(body:TemplateRequest):
    job=get_job(body.job_id)
    pads=[p.model_dump() for p in body.pads]
    with Image.open(job['_image_path']) as image:
        try: validate_pads(pads,*image.size)
        except ValueError as e: raise HTTPException(400,str(e))
        key=uuid4().hex
        data=dict(id=key,name=body.name.strip(),pads=pads,width=image.width,height=image.height,source_job=body.job_id)
        image.save(TEMPLATES/(key+'.png'))
    (TEMPLATES/(key+'.json')).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    return data

app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')
