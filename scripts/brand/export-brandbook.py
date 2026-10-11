"""Export the generated SVG guide to a vector PDF using ReportLab.

Arabic is already shaped into paths in the source; exporting does not depend
on viewer fonts or reverse Arabic strings. Photographs remain raster images.
"""
import base64,io,json,re,sys,xml.etree.ElementTree as ET
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.graphics.svgpath import SvgPath
from reportlab.lib.units import mm

ROOT=Path(__file__).resolve().parents[2]
GUIDE=ROOT/'assets/brand/guide'
OUT=ROOT/'output/pdf/mawrid-brand-book.pdf'
OUT.parent.mkdir(parents=True,exist_ok=True)
WIDTH,HEIGHT=320*mm,200*mm
SCALE=WIDTH/1600
N=lambda e,k,d=0:float(e.get(k,str(d)))
image_cache={}

def draw_path(c,d,fill,stroke,sw):
    shape=SvgPath(d,fillColor=HexColor(fill) if fill!='none' else None)
    p=c.beginPath();index=0
    for op in shape.operators:
        if op==0:p.moveTo(*shape.points[index:index+2]);index+=2
        elif op==1:p.lineTo(*shape.points[index:index+2]);index+=2
        elif op==2:p.curveTo(*shape.points[index:index+6]);index+=6
        elif op==3:p.close()
    c.drawPath(p,stroke=int(stroke!='none'),fill=int(fill!='none'),fillMode=1)

def draw(c,e,inherited=None):
    tag=e.tag.split('}')[-1]
    if tag in ['title','desc','defs']:return
    state=dict(inherited or {'fill':'#000000','stroke':'none','stroke-width':'1','opacity':'1'})
    for key in ['fill','stroke','stroke-width','opacity']:
        if key in e.attrib:state[key]=e.get(key)
    c.saveState()
    for name,args in re.findall(r'(translate|scale|rotate|matrix)\(([^)]+)\)',e.get('transform','')):
        v=[float(x) for x in re.split(r'[ ,]+',args.strip())]
        if name=='translate':c.translate(v[0],v[1] if len(v)>1 else 0)
        elif name=='scale':c.scale(v[0],v[1] if len(v)>1 else v[0])
        elif name=='rotate':c.rotate(v[0])
        else:c.transform(*v)
    fill,stroke,sw=state['fill'],state['stroke'],float(state['stroke-width'])
    if fill!='none':c.setFillColor(HexColor(fill))
    if stroke!='none':c.setStrokeColor(HexColor(stroke))
    c.setLineWidth(sw)
    c.setLineCap({'butt':0,'round':1,'square':2}.get(e.get('stroke-linecap','butt'),0))
    c.setLineJoin({'miter':0,'round':1,'bevel':2}.get(e.get('stroke-linejoin','miter'),0))
    opacity=float(state['opacity']);c.setFillAlpha(opacity);c.setStrokeAlpha(opacity)
    if 'stroke-dasharray'in e.attrib:c.setDash([float(x)for x in e.get('stroke-dasharray').split()])
    if tag=='path':draw_path(c,e.get('d'),fill,stroke,sw)
    elif tag=='rect':
        x,y,w,h=N(e,'x'),N(e,'y'),N(e,'width'),N(e,'height')
        if N(e,'rx'):c.roundRect(x,y,w,h,N(e,'rx'),stroke=int(stroke!='none'),fill=int(fill!='none'))
        else:c.rect(x,y,w,h,stroke=int(stroke!='none'),fill=int(fill!='none'))
    elif tag=='circle':c.circle(N(e,'cx'),N(e,'cy'),N(e,'r'),stroke=int(stroke!='none'),fill=int(fill!='none'))
    elif tag=='image':
        source=e.get('href')or e.get('{http://www.w3.org/1999/xlink}href')
        if source not in image_cache:image_cache[source]=ImageReader(io.BytesIO(base64.b64decode(source.split(',',1)[1])))
        img=image_cache[source];iw,ih=img.getSize();x,y,w,h=N(e,'x'),N(e,'y'),N(e,'width'),N(e,'height')
        fit=e.get('preserveAspectRatio','xMidYMid meet').endswith('meet')
        scale=min(w/iw,h/ih)if fit else max(w/iw,h/ih)
        dw,dh=iw*scale,ih*scale
        clip=c.beginPath();clip.rect(x,y,w,h);c.clipPath(clip,stroke=0)
        # Undo the page's SVG Y direction while painting an image.
        c.translate(x+(w-dw)/2,y+(h-dh)/2+dh);c.scale(1,-1)
        c.drawImage(img,0,0,dw,dh,mask='auto')
    for child in e:draw(c,child,state)
    c.restoreState()

contents=json.loads((GUIDE/'contents.json').read_text(encoding='utf-8'))
c=canvas.Canvas(str(OUT),pagesize=(WIDTH,HEIGHT),pageCompression=1)
c.setTitle('MAWRID — Visual Identity / مورد')
c.setAuthor('MAWRID')
c.setSubject('Brand identity based on the approved green water mark and bright Saudi campus direction.')
for page in contents:
    c.bookmarkPage('page-'+str(page['id']))
    c.addOutlineEntry(page['en'],'page-'+str(page['id']),0)
    c.saveState();c.translate(0,HEIGHT);c.scale(SCALE,-SCALE)
    draw(c,ET.parse(GUIDE/page['file']).getroot())
    c.restoreState();c.showPage()
c.save()
print(f'{len(contents)} vector PDF pages exported: {OUT}')
