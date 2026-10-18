from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
from common import *
s=SVG(420,297,physical=(420,297))
frame(s,1,'SIMPLIFIED PROCESS & INSTRUMENTATION DIAGRAM','NTS')
# Drawing primitives: pressure vessels, isolation valves, check valves, pumps and ISA bubbles.
JUMPS=[]
def pipe(points,col=GRAY,sw=.7,arr='raw'):
 s.path('M'+' L'.join(f'{x} {y}' for x,y in points),col,sw,arrow=arr)
def vjump(x,y0,y1,ys,col=DRAIN,sw=.5,arr='drain',r=1.4):
 d=f'M{x} {y0}'
 for y in sorted(ys):
  if y0+r<y<y1-r:
   curve=f'M{x} {y-r} C{x+2*r} {y-r} {x+2*r} {y+r} {x} {y+r}'
   JUMPS.append((curve,col,sw,None))
   d+=f' L{x} {y-r} C{x+2*r} {y-r} {x+2*r} {y+r} {x} {y+r}'
 d+=f' L{x} {y1}'; s.path(d,col,sw,arrow=arr)
def hjump(x0,x1,y,xs,col=GRAY,sw=.7,arr='raw',r=1.3):
 direction=1 if x1>x0 else -1
 d=f'M{x0} {y}'
 for x in sorted(xs,reverse=direction<0):
  if min(x0,x1)+r<x<max(x0,x1)-r:
   curve=f'M{x-direction*r} {y} C{x-direction*r} {y-2*r} {x+direction*r} {y-2*r} {x+direction*r} {y}'
   JUMPS.append((curve,col,sw,None))
   d+=f' L{x-direction*r} {y} C{x-direction*r} {y-2*r} {x+direction*r} {y-2*r} {x+direction*r} {y}'
 d+=f' L{x1} {y}';s.path(d,col,sw,arrow=arr)
def iso(x,y,vertical=False):
 tr=f'translate({x} {y})'+(' rotate(90)' if vertical else '')
 s.raw(f'<g transform="{tr}"><path d="M-2.2 -1.8 L2.2 1.8 L2.2 -1.8 L-2.2 1.8 Z" fill="white" stroke="{INK}" stroke-width=".35"/></g>')
def check(x,y,reverse=False,vertical=False):
 ang=90 if vertical else (180 if reverse else 0)
 s.raw(f'<g transform="translate({x} {y}) rotate({ang})"><path d="M-2 -1.7 L1.2 0 L-2 1.7 Z M1.8 -2 L1.8 2" fill="white" stroke="{INK}" stroke-width=".4"/></g>')
def pump(x,y,reverse=False):
 s.circle(x,y,4.2,'white',INK,.5)
 if reverse:s.path(f'M{x+2} {y-2.3} L{x-2.3} {y} L{x+2} {y+2.3} Z',INK,.35,fill='#DCEDEE')
 else:s.path(f'M{x-2} {y-2.3} L{x+2.3} {y} L{x-2} {y+2.3} Z',INK,.35,fill='#DCEDEE')
def inst(x,y,tag,panel=False,signal=True):
 s.circle(x,y,5,'white',INK,.35)
 if panel:s.line(x-5,y,x+5,y,INK,.25)
 if '/' in tag:
  parts=tag.split('/');s.text(x,y-.5,parts[0],2.1,anchor='middle',mono=True);s.text(x,y+2.2,parts[1],2.1,anchor='middle',mono=True)
 elif '-' in tag:
  a,b=tag.rsplit('-',1);s.text(x,y-.5,a,2.25,anchor='middle',mono=True);s.text(x,y+2.35,b,2.25,anchor='middle',mono=True)
 else:s.text(x,y+.8,tag,2.2,anchor='middle',mono=True)
 if signal:s.line(x,y-5,x,44,TEAL,.25,dash='1.2 1')
def tap(x,y,ey):s.line(x,y,x,ey,INK,.25)
def sample(x,y,lab):
 pipe([(x,y),(x,y+10)],GRAY,.7,'raw');iso(x,y+5,True)
 s.path(f'M{x-2} {y+11} L{x-1.5} {y+14} L{x+1.5} {y+14} L{x+2} {y+11}',INK,.35)
 s.text(x,y+18,lab,2.3,anchor='middle',mono=True)
def vessel(x,tag,num,w=18):
 s.rect(x-w/2,100,w,37,fill='white',stroke=INK,sw=.45,rx=3)
 s.ellipse(x,103,w/2,3,'#EFF4F4',INK,.35)
 s.line(x-w/2+1,113,x+w/2-1,113,LINE,.3)
 s.line(x-w/2+1,129,x+w/2-1,129,LINE,.3)
 s.text(x,122,tag,2.45,600,'middle',mono=True)
 # Manual multiport head and operator handle.
 s.rect(x-4,92,8,7,fill='white',stroke=INK,sw=.45)
 s.text(x,94.6,'MANUAL',1.4,anchor='middle',mono=True)
 s.text(x,97.7,'MPV',2.0,anchor='middle',mono=True)
 s.num(x,143,num,r=3.1,size=3.3)

# Top control layer: one schematic signal bundle, with individual field drops.
s.rect(142,23,112,15,fill='#EFF6F7',stroke=TEAL,sw=.5,rx=1)
s.num(148,30.5,13,r=3.2,size=3.5)
s.text(155,29,'CP-801  |  LOCAL CONTROL PANEL',3.1,600,mono=True)
s.text(155,34.6,'Controller · HMI · E-stop · beacon · 4G',2.5)
s.line(20,44,409,44,TEAL,.25,dash='1.4 1')
s.line(198,38,198,44,TEAL,.25,dash='1.4 1')
s.circle(198,44,.75,TEAL,TEAL,.2)
s.text(20,41,'SHARED SCHEMATIC SIGNAL BUNDLE — all field inputs and control outputs terminate at CP-801',2.2,fill=TEAL)
# Data line with small repeated circles.
s.line(254,30,306,30,TEAL,.25)
for x in range(259,303,6):s.circle(x,30,.65,'white',TEAL,.25)
s.text(280,26.8,'4G DATA',2.25,anchor='middle',mono=True)
s.path('M311 35 C305 35 304 27 310 26 C310 20 320 20 323 24 C328 19 338 21 340 25 C346 22 356 23 359 27 C365 24 375 26 375 31 C381 31 380 37 374 38 L313 38 C309 38 307 36 311 35 Z',TEAL,.4,fill='#F4F9F9')
s.text(341,29,'MAWRID PLATFORM',2.7,600,'middle')
s.text(341,34,'Monitoring + AI: advises, never decides',2.2,anchor='middle')

# Frame / leak-tray boundary. No process connection is implied by this dashed envelope.
s.rect(107,87,302,105,fill='none',stroke='#A4B7BF',sw=.3,dash='3 1.5')
s.num(147,187,14,r=2.8,size=3.1);s.text(152,188,'SK-901  FRAME + LEAK TRAY',2.3,mono=True,fill=MUTED)

# Continuous main train and right-hand irrigation outlet.
# Lines are drawn first; equipment and valve silhouettes mask their own footprints.
pipe([(93,119),(153,119)])
pipe([(171,119),(195,119)])
pipe([(207,119),(225,119)])
pipe([(243,119),(255,119)])
pipe([(281,119),(291,119)])
pipe([(309,119),(329,119)],PURPLE,.7,'treated')
pipe([(337,119),(354,119)],PURPLE,.7,'treated')
pipe([(380,119),(410,119)],PURPLE,.7,'treated')
s.text(409,142,'DRIP',2.6,600,'end');s.text(409,146,'IRRIGATION',2.3,600,'end')
# Manually isolated intake from underground chamber, with one check after P-101.
pipe([(36,178),(54,178),(54,94),(66,94)])
iso(54,163,True);check(45,178)
# Raw sensing sample manifold taps the T-201 outlet (instrument impulse lines, not process branches).
s.path('M96 119 L96 89',INK,.25)
hjump(96,60,89,[84,70],INK,.25,None,r=1.0)
s.path('M60 89 L60 68 L101 68',INK,.25)
for x in [65,77,89,101]:tap(x,63,68)
# Sensors and taps.
for x,tag in [(65,'AIT-201'),(77,'AIT-202'),(89,'AIT-203'),(101,'TT-201')]:inst(x,58,tag)
s.text(83,74,'RAW: turbidity / pH / EC / °C',2.2,anchor='middle')
inst(70,81,'LSH-201',signal=False);inst(84,81,'LSL-201',signal=False)
s.path('M70 76 L61.2 76 C61.2 73.8 58.8 73.8 58.8 76 L57 76 L57 44',TEAL,.25,dash='1.2 1')
s.path('M84 76 L108 76 L108 44',TEAL,.25,dash='1.2 1')
tap(70,86,93);tap(84,86,93)
inst(132,97,'FT-1');tap(132,102,119)
inst(144,76,'PT-1');s.path('M144 81 L144 119 M144 85 L156 85 L156 81',INK,.25)
inst(156,76,'PI-1',signal=False)
s.text(156,67.6,'LOCAL GAUGE',2.2,anchor='middle')
inst(183,76,'PT-2');tap(183,81,119)
inst(216,76,'PT-4');tap(216,81,119)
inst(249,76,'PT-3');tap(249,81,119)
for x,tag in [(264,'AIT-401'),(275,'XA-401')]:
 inst(x,83,tag);tap(x,88,113)
s.text(268,142.5,'UV intensity / lamp fault',2.2,anchor='middle')
for x,tag in [(282,'AIT-501'),(294,'AIT-502'),(306,'AIT-503'),(318,'TT-501')]:
 inst(x,58,tag);tap(x,63,68)
s.path('M282 68 L318 68 M300 68 L300 109',INK,.25)
s.text(300,146,'Low-range final turbidity',2.2,anchor='middle')
s.text(300,149.5,'+ pH / conductivity / °C',2.2,anchor='middle')
inst(333,87,'ZSO/ZSC');tap(333,92,110)
for x,tag in [(358,'LSH-701'),(375,'LSL-701')]:
 inst(x,76,tag);tap(x,81,103)
inst(402,97,'FT-2');s.path('M402 102 V106 H400 V119',INK,.25)
# A grade line with gaps at unrelated pipes / sensing lines.
for x0,x1 in [(10,18),(22,46),(50,52),(56,59)]:s.line(x0,151,x1,151,MUTED,.3,dash='2 1.3')
s.text(10,149,'GRADE',2.2,fill=MUTED)
# Inlet and underground collection.
s.text(33,108.5,'ABLUTION',2.25,600,'middle');s.text(33,112.1,'+ HAND-WASH',2.05,600,'middle');s.text(33,115.8,'WATER',2.25,600,'middle')
s.path('M10 122 L18.5 122 C18.5 119 21.5 119 21.5 122 L33 122 L33 156',GRAY,.7,arrow='raw')
s.rect(15,156,40,36,fill='#F6F8F9',stroke=INK,sw=.4,dash='2 1.2')
s.line(15,167,55,167,LINE,.25);s.text(34,163,'TR-101',2.5,600,'middle',mono=True)
s.num(11,181,1,r=3,size=3.4)
for x,tag in [(20,'LSH-101'),(47,'LSL-101')]:
 inst(x,138,tag);tap(x,143,156)
pipe([(40.2,178),(54,178),(54,156)])
check(45,178);iso(54,169,True)
s.line(22,178,31.8,178,GRAY,.7,arrow='raw')
pump(36,178);iso(26,178)
s.text(36,187,'P-101',2.5,600,'middle',mono=True);s.num(47,187,2,r=2.8,size=3.1)
s.text(15,196,'UNDERGROUND CHAMBER',2.2,fill=MUTED)
# Equalization tank and main equipment.
s.rect(66,93,27,41,fill='white',stroke=INK,sw=.5,rx=2)
s.ellipse(79.5,96,13.5,3,'#EFF4F4',INK,.35)
s.line(67,111,92,111,LINE,.3)
s.text(79.5,121,'T-201',2.7,600,'middle',mono=True)
s.text(79.5,126,'5 m³',2.4,anchor='middle');s.num(79.5,141,3,r=3,size=3.5)
pump(112,119);s.text(112,110,'P-102',2.5,600,'middle',mono=True);s.num(112,134,4,r=3,size=3.5)
iso(104,119);check(121,119);iso(127,119)
vessel(162,'F-301',5);vessel(234,'F-302',7)
for x in [149,175,191,211,221,246,252,285]:iso(x,119)
s.rect(195,105,12,29,fill='white',stroke=INK,sw=.45,rx=3)
for x in [198,201,204]:s.line(x,109,x,130,LINE,.3)
s.text(201,140,'F-303',2.5,600,'middle',mono=True);s.num(201,147,6,r=3,size=3.4)
s.rect(255,113,26,12,fill='white',stroke=INK,sw=.45,rx=4)
s.line(258,116,278,116,PURPLE,.4);s.line(258,122,278,122,PURPLE,.4)
s.text(268,120,'UV-401',2.45,600,'middle',mono=True);s.num(268,135,8,r=3,size=3.4)
s.rect(291,109,18,20,fill='#F0EAF7',stroke=PURPLE,sw=.5,rx=2)
s.text(300,119,'AT-501',2.45,600,'middle',mono=True);s.text(300,124,'VERIFY',2.2,anchor='middle');s.num(300,137,9,r=3,size=3.4)
# Fail-closed, spring-return ball valve and its actuator.
s.circle(333,119,3.6,'white',INK,.45);s.path('M330.5 117 L335.5 121 M330.5 121 L335.5 117',INK,.4)
s.line(333,115.4,333,113,INK,.4);s.rect(329.5,109.5,7,3.5,fill='white',stroke=INK,sw=.35)
s.path('M330 109.5 L331 108 L332 109.5 L333 108 L334 109.5 L335 108',INK,.35)
s.text(328,104.5,'XV-601',2.5,600,'end',mono=True)
s.text(333,128.5,'FC — FAIL CLOSED',2.35,600,'middle',fill=PURPLE)
s.text(333,132.5,'SPRING RETURN',2.2,anchor='middle');s.num(333,140,10,r=3,size=3.4)
# Treated tank and irrigation pump.
s.rect(354,103,26,32,fill='white',stroke=PURPLE,sw=.5,rx=2)
s.line(355,112,379,112,'#CBBADD',.4)
s.text(367,121,'T-701',2.5,600,'middle',mono=True);s.text(367,127,'2 m³',2.4,anchor='middle')
s.num(371,142,12,r=3,size=3.4)
pump(395,119);iso(386,119);check(403,119);iso(408,119)
s.text(395,132,'P-104',2.5,600,'middle',mono=True)
# Sample taps are distinct, capped sample outlets.
for x,lab in [(98,'SP-1'),(216,'SP-2'),(249,'SP-3'),(314,'SP-4')]:sample(x,119,lab)
# Reject branch, center-hold three-way valve, and selectable dual-duty P-103 manifold.
pipe([(319,119),(319,148),(348,148),(348,160),(334,160)],GRAY,.7,'raw')
s.circle(330,160,4,'white',INK,.45)
s.path('M326 160 L330 160 L330 164 M330 160 L334 160',INK,.4)
s.rect(327,151,6,4,fill='white',stroke=INK,sw=.35);s.line(330,155,330,156,INK,.35)
s.text(336,168,'XV-602',2.5,600,mono=True)
s.text(336,172,'3-way + HOLD',2.2)
s.text(336,176,'interlocked modes',2.2)
# One port routes to reprocess pump suction; another drops to drain.
pipe([(326,160),(285,160),(285,180),(273.2,180)])
iso(285,170,True)
pipe([(367,135),(367,180),(273.2,180)],PURPLE,.7,'treated');iso(367,171,True)
s.text(368.5,175,'BW SUPPLY',2.1,mono=True,fill=PURPLE)
pump(269,180,True);iso(279,180);check(259,180,reverse=True);iso(253,180)
s.text(269,172,'P-103',2.5,600,'middle',mono=True);s.num(283,188,11,r=3,size=3.4)
# Reprocessing discharge returns to tank. Gaps are deliberate line jumps at drain crossings.
hjump(264.8,62,180,[139],GRAY,.7,'raw')
pipe([(62,180),(62,128),(66,128)])
iso(239,180)
s.text(154,176,'REPROCESS RETURN TO T-201',2.3,mono=True)
# Backwash: separate manually selected manifold to media multiport heads.
pipe([(247,180),(247,164)])
iso(247,171,True)
hjump(247,146,164,[],GRAY,.7,'raw')
s.path('M146 164 L146 120.5 C143.2 120.5 143.2 117.5 146 117.5 L146 94 L158 94',GRAY,.7,arrow='raw')
s.path('M180 164 L180 120.3 C182 120.3 182 117.7 180 117.7 L180 102',GRAY,.7,arrow='raw')
hjump(180,223,102,[183,216],GRAY,.7,'raw')
pipe([(223,102),(223,94),(230,94)])
iso(146,153,True);iso(180,153,True)
s.text(184,160,'BACKWASH MANIFOLD',2.2,mono=True)
s.text(253,205,'Manual manifold: one duty at a time; select matching suction and discharge valves.',2.2,anchor='middle')
# Process drains: overflow, media rinse, rejection and leak tray.
pipe([(15,165),(7,165),(7,198)],DRAIN,.5,'drain')
pipe([(66,105),(60,105),(60,198)],DRAIN,.5,'drain')
pipe([(166,95),(171,95),(171,90)],DRAIN,.5,'drain')
pipe([(238,95),(247,95),(247,90)],DRAIN,.5,'drain')
hjump(247,139,90,[216,183,144],DRAIN,.5,'drain')
s.circle(171,90,.65,DRAIN,DRAIN,.1)
vjump(139,90,198,[119])
vjump(330,164,198,[180])
# Treated-tank overflow discharges without crossing the main feed or inlet.
s.line(380,106,381,106,DRAIN,.5);vjump(381,106,198,[119],r=1.2)
pipe([(388,192),(388,198)],DRAIN,.5,'drain')
# Common drain collection header ends above a visibly separated receptor.
hjump(7,391,198,[],DRAIN,.5,'drain')
s.num(18,204,15,r=2.8,size=3.1);s.text(24,205,'DR-001  |  OVERFLOW + BACKWASH + REJECT + TRAY',2.3,mono=True)
s.path('M391 198 L397 198 L397 200',DRAIN,.5,arrow='drain')
s.path('M393 203 L395 205 L399 205 L401 203 M397 205 L397 207 L410 207',DRAIN,.5,arrow='drain')
s.text(391,194.5,'AG',2.4,600,mono=True);s.text(406,202,'AIR GAP',2.2,anchor='end')
s.text(409,211,'SANITARY SEWER',2.2,anchor='end')
# Referenced output terminals share the CP-801 signal bundle.
s.rect(20,23,111,14,fill='white',stroke=TEAL,sw=.3)
s.text(23,27,'CP-801 OUTPUT NET REFERENCES O1–O7',2.4,600,fill=TEAL)
s.text(23,31,'O1 P-101 · O2 P-102 · O3 P-103 · O4 P-104',2.3,mono=True)
s.text(23,35,'O5 XV-601 · O6 XV-602 · O7 UV-401',2.3,mono=True)
s.line(125,37,125,44,TEAL,.25,dash='1.2 1')
# Dashed terminal leads connect keyed output nets to each actuator.
for pts in [[(39,174.7),(39,175.2)],[(115,123.3),(114.5,122.4)],[(265.2,184.8),(266,183)],[(392,123.7),(392.5,122.4)],[(336.3,114),(336,113)],[(333.3,151),(333,152)],[(281,126.3),(280,124.8)]]:
 s.path('M'+' L'.join(f'{x} {y}' for x,y in pts),TEAL,.25,dash='0.5 .4')
# Output terminal bubbles carry the exact same net references as CP-801.
for x,y,lab in [(39,173,'O1'),(115,125,'O2'),(264,186,'O3'),(391,125,'O4'),(338,114,'O5'),(335,151,'O6'),(281,128,'O7')]:
 s.circle(x,y,1.7,'white',TEAL,.25);s.text(x,y+.65,lab,1.8,anchor='middle',fill=TEAL,mono=True)


# Lower-left component schedule: canonical numbering, tags and names on every sheet.
s.text(10,213,'NUMBERED COMPONENT REFERENCE',3.1,600)
s.rect(10,215,199,62,fill='white',stroke=LINE,sw=.3)
for i,(n,tag,name,_) in enumerate(COMPONENTS):
 y=218.4+i*3.85
 if i%2==0:s.rect(10.2,y-2.75,198.6,3.85,fill='#F5F8F9',stroke='none')
 s.num(13.4,y-1,n,r=1.65,size=2.0)
 s.text(17,y,tag,2.25,mono=True)
 s.text(51,y,name,2.25)
# Protection logic, complete and independently understandable.
s.text(215,215,'LOCAL PROTECTION LOGIC',3.1,600)
s.rect(215,217,195,44.2,fill='white',stroke=INK,sw=.3)
s.rect(215,217,195,5,fill='#EAF1F3',stroke='none')
s.line(280,217,280,261.2,LINE,.25)
s.text(218,220.5,'CONDITION',2.45,600);s.text(283,220.5,'RESPONSE',2.45,600)
rows=[
('Power loss','XV-601 spring-closes; all pumps stop.'),
('Final turbidity above limit','XV-602 → reprocess; after 3 attempts: HOLD + alarm.'),
('UV <70% or lamp fault','Immediate HOLD + alarm + maintenance request.'),
('Critical sensor lost / frozen / low confidence','Immediate HOLD + calibration request.'),
('High filter differential pressure','Backwash; if persistent, issue a service alert.'),
('T-201 low level','Stop P-102 to prevent dry running.'),
('T-701 full','Pause the treatment train.'),
('XV-601 closure not confirmed','Critical alarm + stop all pumps.')]
for i,(a,b) in enumerate(rows):
 y=225.5+i*4.8
 if i%2==0:s.rect(215.2,y-3.45,194.6,4.8,fill='#F7F9FA',stroke='none')
 s.text(218,y,a,2.16 if i==3 else 2.28);s.text(283,y,b,2.28)
 s.line(215,y+1.2,410,y+1.2,LINE,.18)
# Clear legend and fixed control statement.
s.text(10,281,'RAW / PROCESS',2.2,fill=GRAY);s.line(42,280.2,57,280.2,GRAY,.7,arrow='raw')
s.text(61,281,'TREATED',2.2,fill=PURPLE);s.line(82,280.2,97,280.2,PURPLE,.7,arrow='treated')
s.text(101,281,'DRAIN',2.2);s.line(118,280.2,133,280.2,DRAIN,.5,arrow='drain')
s.text(137,281,'SIGNAL',2.2);s.line(155,280.2,170,280.2,TEAL,.25,dash='1.2 1')
s.text(174,281,'○ field   ⊖ panel   ∩ no connection',2.2)
s.text(215,265.2,'Default / any fault: XV-601 CLOSED. HOLD: XV-602 shut; pumps stopped.',2.25,600)
s.text(215,269.0,'Fixed rules in the local controller authorize irrigation, even offline.',2.25,600)
s.text(215,272.7,'AI may only make the decision more conservative.',2.25,600)
# Compact titleblock to preserve the complete safety table.
s.rect(272,275,138,9,fill='white',stroke=INK,sw=.3)
s.text(275,278.5,'PROJECT: MAWRID  |  SIMPLIFIED P&ID',2.5,600)
s.text(275,282.4,f'1/3  |  REV A  |  {DATE}  |  NTS  |  COMPETITION CONCEPT',2.18,mono=True)
# Restore localized bridge strokes above all crossing lines.
JUMPS += [
 ('M18.5 122 C18.5 119 21.5 119 21.5 122',GRAY,.7,None),
 ('M61.2 76 C61.2 73.8 58.8 73.8 58.8 76',TEAL,.25,'1.2 1'),
 ('M146 120.5 C143.2 120.5 143.2 117.5 146 117.5',GRAY,.7,None),
 ('M180 120.3 C182 120.3 182 117.7 180 117.7',GRAY,.7,None),
]
for curve,col,sw,dash in JUMPS:
 s.path(curve,'white',sw+.65)
 s.path(curve,col,sw,dash=dash)
s.save('sheet-1-pid.svg')
