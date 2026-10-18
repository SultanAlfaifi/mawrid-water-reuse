from pathlib import Path
import base64, html, csv, json
OUT = Path(__file__).resolve().parent.parent
ROOT = OUT.parents[2]
FONT = ROOT / 'assets/fonts'
INK='#24343F'; GRAY='#3E4A52'; MUTED='#61717E'; LINE='#C6D2D9'; TEAL='#147B80'; PURPLE='#7752AA'; PALE='#EFF6F7'; DRAIN='#172129'; AMBER='#A6651C'
COMPONENTS = [
(1,'TR-101','Collection chamber & trap','Collect ablution and hand-wash water; retain coarse and floating solids.'),
(2,'P-101','Submersible lift pump','Lift collected water to the equalization tank.'),
(3,'T-201','Equalization tank','Buffer prayer-time inflow surges and measure raw-water properties.'),
(4,'P-102','Feed pump','Feed the treatment train at a controlled flow.'),
(5,'F-301','Multimedia sand filter','Reduce turbidity and suspended solids.'),
(6,'F-303','5 µm PP cartridge filter','Retain fine particles after sand filtration and before carbon / Biochar adsorption.'),
(7,'F-302','Carbon / palm Biochar filter','Adsorb targeted dissolved and organic constituents.'),
(8,'UV-401','UV disinfection reactor','Inactivate microorganisms.'),
(9,'AT-501','Verification cell','Measure final turbidity, pH, conductivity and temperature.'),
(10,'XV-601 / XV-602','Irrigation + diversion valves','Select irrigation, reprocessing, holding or drain diversion.'),
(11,'P-103','Backwash / reprocess pump','Backwash media and return off-specification water.'),
(12,'T-701 / P-104','Treated-water tank + irrigation pump','Provide short-term storage and feed drip irrigation.'),
(13,'CP-801','Control panel','Local controller, HMI, emergency stop, status beacon and 4G platform link.'),
(14,'SK-901','Frame + leak tray','Support equipment and collect leaks.'),
(15,'DR-001','Drain lines','Route overflow, backwash and diversion to the sewer through an air gap.')]
DISCLAIMER='Competition concept — not approved for construction. Dimensions approximate, based on common commercial sizes.'
DATE='2026-10-15'
def esc(s): return html.escape(str(s),quote=True)
class SVG:
 def __init__(self,w,h,physical=None,bg=True):
  self.w,self.h=w,h; self.a=[]; self.texts=[]
  dims=f'width="{physical[0]}mm" height="{physical[1]}mm"' if physical else f'width="{w}" height="{h}"'
  self.a.append(f'<svg xmlns="http://www.w3.org/2000/svg" {dims} viewBox="0 0 {w} {h}" role="img">')
  self.a.append('<title>MAWRID | Water recovery unit — competition concept</title><desc>Original vector engineering concept. All text in English. Numbered components correspond to components.csv.</desc>')
  f1=base64.b64encode((FONT/'plex-arabic-400.ttf').read_bytes()).decode(); f2=base64.b64encode((FONT/'plex-arabic-600.ttf').read_bytes()).decode()
  self.a.append(f'<defs><style>@font-face{{font-family:Plex;src:url(data:font/ttf;base64,{f1}) format("truetype");font-weight:400}}@font-face{{font-family:Plex;src:url(data:font/ttf;base64,{f2}) format("truetype");font-weight:600}}text{{font-family:Plex,"IBM Plex Sans Arabic",sans-serif;fill:{INK};direction:ltr}}.mono{{font-family:Menlo,"Courier New",monospace}}.num{{font-family:Arial,sans-serif;font-weight:bold}}</style>')
  for key,col in [('raw',GRAY),('treated',PURPLE),('drain',DRAIN),('teal',TEAL),('dim',MUTED)]:
   self.a.append(f'<marker id="a-{key}" markerWidth="5" markerHeight="5" refX="4.7" refY="2.5" orient="auto-start-reverse" markerUnits="strokeWidth"><path d="M0 0 L5 2.5 L0 5 Z" fill="{col}"/></marker>')
  self.a.append('<pattern id="hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" stroke="#BDD4D3" stroke-width="0.6"/></pattern></defs>')
  if bg:self.rect(0,0,w,h,fill='white',stroke='none',cls='sheet-background')
 def raw(self,s): self.a.append(s)
 def rect(self,x,y,w,h,fill='white',stroke=INK,sw=.4,rx=0,cls=None,dash=None):
  self.a.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"'+(f' class="{cls}"' if cls else '')+(f' stroke-dasharray="{dash}"' if dash else '')+'/>')
 def circle(self,x,y,r,fill='white',stroke=INK,sw=.4): self.a.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
 def ellipse(self,x,y,rx,ry,fill='none',stroke=INK,sw=.4): self.a.append(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
 def path(self,d,color=GRAY,sw=.7,fill='none',dash=None,arrow=None,opacity=None):
  self.a.append(f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"'+(f' stroke-dasharray="{dash}"' if dash else '')+(f' marker-end="url(#a-{arrow})"' if arrow else '')+(f' opacity="{opacity}"' if opacity else '')+'/>')
 def line(self,x1,y1,x2,y2,color=GRAY,sw=.7,dash=None,arrow=None):self.path(f'M{x1} {y1} L{x2} {y2}',color,sw,dash=dash,arrow=arrow)
 def text(self,x,y,s,size=3,weight=400,anchor='start',fill=INK,mono=False,rotate=None):
  idx=len(self.texts); self.texts.append(dict(x=x,y=y,text=str(s),size=size))
  self.a.append(f'<text id="txt-{idx}" x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" style="fill:{fill}"'+(' class="mono"' if mono else '')+(f' transform="rotate({rotate} {x} {y})"' if rotate else '')+f'>{esc(s)}</text>')
 def lines(self,x,y,lines,size=3,leading=None,**kw):
  for i,t in enumerate(lines):self.text(x,y+i*(leading or size*1.4),t,size,**kw)
 def num(self,x,y,n,r=3.4,size=3.8,fill=TEAL):
  self.raw(f'<g data-component="{n}" aria-label="{chr(0x2460+n-1)} {esc(COMPONENTS[n-1][2])}">')
  self.circle(x,y,r,'white',fill,.45 if r<10 else 2.2)
  self.text(x,y+size*.34,str(n),size,600,'middle',fill)
  self.raw('</g>')
 def component(self,n,x,y,name_lines=None,size=2.5,tag_size=2.5,anchor='middle'):
  row=COMPONENTS[n-1]; self.text(x,y,row[1],tag_size,600,anchor,mono=True)
  self.lines(x,y+size*1.5,name_lines or [row[2]],size,anchor=anchor)
 def save(self,name):
  self.a.append('</svg>'); (OUT/name).write_text('\n'.join(self.a)); (OUT/'review'/f'{name}.text.json').write_text(json.dumps(self.texts,indent=2))
def frame(s,sheet,title,scale):
 s.rect(5,5,410,287,fill='none',stroke=INK,sw=.35)
 s.text(10,13,'MAWRID',6,600); s.text(51,12.6,title,4.5,600)
 s.text(409,12.8,f'{sheet} / 3',4,600,'end',fill=TEAL)
 s.line(10,17,410,17,LINE,.3)
 s.text(10,288,DISCLAIMER,2.45,fill=MUTED)
def titleblock(s,sheet,title,scale,y=264):
 s.rect(272,y,138,18,fill='white',stroke=INK,sw=.3)
 s.line(272,y+7,410,y+7,INK,.25)
 s.text(275,y+4.8,'PROJECT: MAWRID',3,600);s.text(407,y+4.8,'STATUS: COMPETITION CONCEPT',2.6,600,'end')
 s.text(275,y+11.4,title,2.65,600)
 s.text(275,y+15.8,f'SHEET {sheet}/3  |  REV A  |  {DATE}  |  SCALE {scale}',2.45,mono=True)
def write_csv():
 with (OUT/'components.csv').open('w',encoding='utf-8-sig',newline='') as f:
  wr=csv.writer(f);wr.writerow(['Number','Tag','Component','Function'])
  for n,t,c,fun in COMPONENTS:wr.writerow([chr(0x2460+n-1),t,c,fun])
if __name__=='__main__':write_csv()
