from pathlib import Path
import xml.etree.ElementTree as ET
import csv, json, re
from PIL import Image
from pypdf import PdfReader
from common import COMPONENTS, OUT
ns={'s':'http://www.w3.org/2000/svg'}
results=[]
for name in ['sheet-1-pid','sheet-2-ga','sheet-3-slide','sheet-3-slide-transparent']:
 root=ET.parse(OUT/(name+'.svg')).getroot()
 nums={int(g.attrib['data-component']) for g in root.iter() if 'data-component' in g.attrib}
 assert nums==set(range(1,16)),(name,nums)
 texts=' '.join(''.join(t.itertext()) for t in root.findall('.//s:text',ns))
 assert not re.search(r'[\u0600-\u06FF]',texts),name
 assert 'Competition concept' in texts and 'not approved for construction' in texts,name
 if name in ['sheet-1-pid','sheet-2-ga']:
  assert root.attrib['width']=='420mm' and root.attrib['height']=='297mm'
 else:assert root.attrib['viewBox']=='0 0 1920 1080'
 for n,tag,comp,fn in COMPONENTS:
  assert any(g.attrib.get('aria-label','')==chr(0x2460+n-1)+' '+comp for g in root.iter()),(name,n,comp)
 im=Image.open(OUT/(name+'.png'))
 assert im.size==((1920,1080) if 'slide' in name else (4961,3508)),(name,im.size)
 assert abs(im.info['dpi'][0]-300)<0.01
 if name.endswith('transparent'):assert im.mode=='RGBA' and im.getpixel((0,0))[3]==0
 if name=='sheet-1-pid':
  for tag in ['LSH-101','LSL-101','LSH-201','LSL-201','AIT-201','AIT-202','AIT-203','TT-201','FT-1','PT-1','PT-2','PT-3','PT-4','AIT-401','XA-401','AIT-501','AIT-502','AIT-503','TT-501','ZSO','ZSC','FT-2','LSH-701','LSL-701','SP-1','SP-2','SP-3','SP-4','FC','AG']:
   assert re.sub(r'[\s-]','',tag) in re.sub(r'[\s-]','',texts),(name,tag)
 results.append({'file':name,'numbered_components':15,'png_size':im.size,'dpi':im.info['dpi'][0],'english_text':True,'process_arrow_segments':sum('marker-end' in g.attrib for g in root.iter())})
rows=list(csv.DictReader((OUT/'components.csv').open(encoding='utf-8-sig')))
assert len(rows)==15
for row,(n,tag,comp,fn) in zip(rows,COMPONENTS):
 assert row==dict(Number=chr(0x2460+n-1),Tag=tag,Component=comp,Function=fn)
pdf=PdfReader(OUT/'mawrid-engineering.pdf');assert len(pdf.pages)==2
for p in pdf.pages:
 w,h=float(p.mediabox.width)*25.4/72,float(p.mediabox.height)*25.4/72
 assert abs(w-420)<.3 and abs(h-297)<.3,(w,h)
 assert len(p.extract_text())>1000
results.append({'pdf_pages':2,'page_size_mm':[round(w,2),round(h,2)],'searchable_text':True,'csv_rows':15})
(OUT/'review'/'verification.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
