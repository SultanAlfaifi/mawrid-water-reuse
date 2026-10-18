"""Original M20 general-arrangement drawing. Model coordinates use 40 mm/m."""
from common import *

s=SVG(420,297,physical=(420,297))
frame(s,2,'M20 GENERAL ARRANGEMENT','1:25')

def dimh(x1,x2,y,ext1,ext2,label):
    s.line(x1,ext1,x1,y+1,MUTED,.19)
    s.line(x2,ext2,x2,y+1,MUTED,.19)
    s.raw(f'<path d="M{x1} {y}H{x2}" fill="none" stroke="{MUTED}" stroke-width=".22" marker-start="url(#a-dim)" marker-end="url(#a-dim)"/>')
    s.rect((x1+x2)/2-5.9,y-3.1,11.8,3.8,'white','none')
    s.text((x1+x2)/2,y-.4,label,2.5,600,'middle',fill=MUTED)

def dimv(x,y1,y2,ext1,ext2,label):
    s.line(ext1,y1,x+1,y1,MUTED,.19)
    s.line(ext2,y2,x+1,y2,MUTED,.19)
    s.raw(f'<path d="M{x} {y1}V{y2}" fill="none" stroke="{MUTED}" stroke-width=".22" marker-start="url(#a-dim)" marker-end="url(#a-dim)"/>')
    s.text(x-1.1,(y1+y2)/2,label,2.5,600,'middle',fill=MUTED,rotate=-90)

def leader(x1,y1,x2,y2,tx,ty,txt,size=2.3):
    s.path(f'M{x1} {y1}L{x2} {y2}',MUTED,.22)
    s.circle(x1,y1,.55,MUTED,'none')
    s.text(tx,ty,txt,size,fill=MUTED)

def pump(x,y,n,tag,tag_dy=6.1):
    s.circle(x,y,3.2,PALE,INK,.35)
    s.path(f'M{x-1.1} {y-1.6}L{x+1.7} {y}L{x-1.1} {y+1.6}Z',INK,.25,TEAL)
    s.num(x-5,y-4.9,n,r=2.6,size=2.8)
    s.text(x,y+tag_dy,tag,2.1,600,'middle',mono=True)

# Panel boundaries and reading guide.
s.line(329,20,329,261,LINE,.3)
s.text(11,21.5,'PLAN',3.3,600)
s.text(11,25.4,'Scale 1:25 · all dimension arrows in metres',2.15,fill=MUTED)

# PLAN: 3.00 x 1.40 skid at x112..232, y40..96.
# All physical objects and clearances below use 40 drawing-mm per model metre.
skx,sky,skw,skd=112,40,120,56
# Service area: 0.30 rear, 0.90 front and 0.60 at each end.
s.rect(88,28,168,104,fill='#F3F8F8',stroke=TEAL,sw=.3,dash='2 1')
s.rect(88,28,168,104,fill='url(#hatch)',stroke='none')
s.rect(skx,sky,skw,skd,fill='white',stroke=INK,sw=.6)
s.rect(skx+1.5,sky+1.5,skw-3,skd-3,fill='#F7F9FA',stroke=LINE,sw=.25)
for px,py in [(112,40),(229.6,40),(112,93.6),(229.6,93.6),(174.8,40)]:
    s.rect(px,py,2.4,2.4,fill=GRAY,stroke=GRAY,sw=.15)
# Cable tray stays completely to the rear, away from the vessels.
s.rect(116,42,110,3.2,fill='#E1E8EE',stroke=MUTED,sw=.3)
for x in range(118,227,5):s.line(x,42.5,x,44.7,MUTED,.18)
s.text(171,38.5,'REAR CABLE TRAY',2.15,600,'middle',fill=MUTED)
s.num(109,46,14,r=2.6,size=2.8)
s.text(117,50,'SK-901',2.3,600,mono=True)

# Tanks and filter vessels in plan.
s.circle(50,68,38,fill='#F2F7F8',stroke=INK,sw=.5)
s.circle(50,68,36.3,fill='none',stroke=LINE,sw=.25)
s.circle(50,68,6.0,fill='white',stroke=MUTED,sw=.3)
s.num(50,44,3,r=3.2,size=3.4)
s.text(50,54,'T-201',3.1,600,'middle',mono=True)
s.text(50,84,'5 m³',3.2,600,'middle')
s.text(50,89,'Ø 1.90 m',2.7,anchor='middle',fill=MUTED)
for n,cx,rad,tag in [(5,132,8.12,'F-301'),(7,184,9.14,'F-302')]:
    s.circle(cx,66,rad,fill='#EAF4F3',stroke=INK,sw=.5)
    s.circle(cx,66,2.5,fill='white',stroke=INK,sw=.3)
    s.num(cx-8.4,55.5,n,r=2.6,size=2.8)
    s.text(cx,80,tag,2.35,600,'middle',mono=True)
    # Front-facing operator hardware, a compact GA symbol, not process piping.
    s.rect(cx-7.1,83,14.2,5.8,fill='white',stroke=MUTED,sw=.25)
    s.text(cx,87,'V / P / SP',1.9,600,'middle',mono=True)
s.circle(158,66,3.6,fill='#F1EEF7',stroke=INK,sw=.4)
s.num(158,55.5,6,r=2.6,size=2.8)
s.text(158,73.5,'F-303',2.1,600,'middle',mono=True)
# 0.95 m UV reactor, 0.089 m diameter.
s.rect(192,91,38,3.56,fill='#EEE8F6',stroke=PURPLE,sw=.4,rx=1.78)
s.num(211,101,8,r=2.6,size=2.8)
s.text(211,108,'UV-401',2.2,600,'middle',mono=True)
s.rect(210,62,10,8,fill='#F1EEF7',stroke=PURPLE,sw=.4,rx=.8)
s.num(216,55.5,9,r=2.6,size=2.8)
s.text(215,75.3,'AT-501',2.05,600,'middle',mono=True)
# Valve assembly and side/rear-mounted control enclosure.
s.path('M222 76L224 78L222 80ZM226 76L224 78L226 80Z',PURPLE,.35,'white')
s.num(224,87.9,10,r=2.6,size=2.8)
s.rect(228,49,4,24,fill='#E8F2F2',stroke=INK,sw=.5)
s.num(242,56,13,r=2.6,size=2.8)
s.text(242,63,'CP-801',2.15,600,'middle',mono=True)
pump(119,85,4,'P-102')
pump(160,86,11,'P-103')

# Treated water tank and irrigation pump.
s.rect(256,44,64,48,fill='#F3EFF8',stroke=PURPLE,sw=.5,rx=2)
s.rect(259,47,58,42,fill='none',stroke=LINE,sw=.25,rx=1)
s.circle(288,62,5,fill='white',stroke=PURPLE,sw=.3)
s.num(270,54,12,r=3.2,size=3.4)
s.text(288,76,'T-701',3,600,'middle',mono=True)
s.text(288,83,'2 m³',3,600,'middle')
pump(288,110,12,'P-104')
s.text(288,124,'Right of skid',2.3,anchor='middle',fill=MUTED)

# Underground collection chamber in plan; distinct from hatched service aisle.
s.rect(20,114,48,32,fill='#F4F6F7',stroke=MUTED,sw=.4,dash='2 1.3')
s.num(25,120,1,r=2.6,size=2.8)
s.text(44,120.7,'TR-101',2.4,600,'middle',mono=True)
s.text(44,127,'BELOW GRADE',2.15,600,'middle',fill=MUTED)
pump(54,137,2,'P-101')
s.text(24,140,'Trap',2.2,fill=MUTED)
s.line(35,130,35,143,MUTED,.35)

# Drain assembly and open-front fold-down service step.
s.rect(122,100,73,11,fill='#DFEAEE',stroke=MUTED,sw=.35,dash='1.6 1')
s.line(122,100,195,100,INK,.5)
s.text(158.5,106.7,'FOLDING STEP',2.4,600,'middle')
s.rect(235,110,15,5.8,fill='white',stroke=DRAIN,sw=.3)
s.num(243,121,15,r=2.6,size=2.8)
s.text(242.5,114.1,'DN50',2.1,600,'middle',mono=True)
s.text(179,116.5,'FRONT / OPERATOR SIDE',2.5,600,'middle',fill=TEAL)
s.text(179,121,'Valves, gauges and sample points face front',2.2,anchor='middle',fill=MUTED)
s.text(179,126,'Hatched area: required clear service aisle',2.2,anchor='middle',fill=MUTED)

# Plan dimensions. Commercial exact dimensions are retained in the specification key.
dimh(12,320,22.5,29,43,'7.70')
dimh(12,88,110,106,104,'1.90')
dimh(112,232,136,132,132,'3.00')
dimh(256,320,97,92,92,'1.60')
dimh(88,112,31,33,35,'0.60')
dimh(232,256,31,35,33,'0.60')
dimv(86,28,40,88,88,'0.30')
dimv(82,96,132,88,88,'0.90')
dimv(104,40,96,112,112,'1.40')
dimv(324,44,92,320,320,'1.20')
dimh(20,68,151,146,146,'1.20')

# FRONT ELEVATION. Datum 240; exact model heights converted at 40 mm/m.
g=240
s.text(11,157,'FRONT ELEVATION',3.3,600)
s.line(11,g,326,g,INK,.5)
for x in range(11,326,9):s.line(x,g+.7,x-2,g+2.6,LINE,.22)

# Clear service envelope intentionally extends above the 2.20 m posts.
s.rect(121,141.6,74,20,fill='#EDF7F7',stroke=TEAL,sw=.3,dash='2 1.2')
s.text(158,147.5,'OPEN SERVICE ZONE',2.5,600,'middle',fill=TEAL)
s.text(158,152.3,'NO OVERHEAD BEAM',2.15,600,'middle',fill=TEAL)
s.text(158,156.7,'Top of envelope +2.46 m',2.2,anchor='middle',fill=TEAL)

# Rear columns are drawn first and masked by equipment; no top spanning member.
for x in [112,174.8,229.6]:
    s.rect(x,152,2.4,88,fill='#D7E1E6',stroke=MUTED,sw=.35)
s.rect(114.4,211.5,115.2,2.4,fill='#E6ECEF',stroke=MUTED,sw=.3)
s.rect(112,236.4,120,3.6,fill='#D4DFE4',stroke=INK,sw=.5)
s.num(115.5,230.8,14,r=2.6,size=2.8)
# Rear cable tray at +1.30, behind objects and never above vessel heads.
s.rect(116,187,109,3,fill='#DEE7EC',stroke=MUTED,sw=.25,dash='1.4 .8')

# Equalization tank. Discrete plan/elevation badges refer to same item.
s.rect(12,160,76,80,fill='#EFF6F7',stroke=INK,sw=.5,rx=5)
s.ellipse(50,165,36.3,4.4,fill='none',stroke=LINE,sw=.3)
s.num(26,179,3,r=3.2,size=3.4)
s.text(50,190,'T-201',3.6,600,'middle',mono=True)
s.text(50,197,'5 m³',3.2,600,'middle')
s.text(50,203,'Equalization tank',2.9,anchor='middle')

# Cylinders: 0.09 m bearing datum + 1.651 m vessel + 0.22 m head.
for n,cx,diam,tag in [(5,132,.406,'F-301'),(7,184,.457,'F-302')]:
    width=diam*40; top=236.4-1.651*40
    s.rect(cx-width/2,top,width,66.04,fill='#EAF4F3',stroke=INK,sw=.5,rx=width*.42)
    s.line(cx-width/2+1,top+8,cx+width/2-1,top+8,LINE,.25)
    s.line(cx-width/2+1,232.8,cx+width/2-1,232.8,LINE,.25)
    s.rect(cx-3.7,top-8.8,7.4,8.8,fill='white',stroke=INK,sw=.4,rx=.6)
    s.line(cx-5.1,top-6,cx+5.1,top-6,INK,.55)
    s.circle(cx+3.5,top-3.2,1.35,fill='white',stroke=INK,sw=.3)
    s.num(cx,188,n,r=3.2,size=3.4)
    s.text(cx,198,tag,2.5,600,'middle',mono=True)
    s.text(cx,202.8,'1665' if n==5 else '1865',2.3,anchor='middle',fill=MUTED)
    s.circle(cx+2.3,209,1.4,fill='white',stroke=INK,sw=.25)
    s.line(cx+2.3,209,cx+3.1,208.2,INK,.2)
    s.path(f'M{cx-2.5} 214V217H{cx-.5}',INK,.35)
    s.text(cx,222,'FRONT',1.8,600,'middle',fill=MUTED)

# Cartridge, horizontal UV reactor and verification assembly.
s.rect(154.4,183,7.2,24.8,fill='#F1EEF7',stroke=PURPLE,sw=.4,rx=2)
s.rect(154.4,183,7.2,3,fill='#E3D9EF',stroke=PURPLE,sw=.35)
s.num(158,176,6,r=2.6,size=2.8)
s.text(158,210.7,'F-303',2.15,600,'middle',mono=True)
s.rect(194,229,38,3.56,fill='#EEE8F6',stroke=PURPLE,sw=.4,rx=1.78)
s.num(199,224,8,r=2.6,size=2.8)
s.text(211,225,'UV-401',2.1,600,'middle',mono=True)
s.rect(207,205,11,8,fill='#F3EFF8',stroke=PURPLE,sw=.4,rx=1)
s.num(204,207,9,r=2.6,size=2.8)
s.text(212.5,202.5,'AT-501',2.15,600,'middle',mono=True)
s.path('M220 215L223 217L220 219ZM226 215L223 217L226 219Z',PURPLE,.4,'white')
s.line(223,217,223,212,PURPLE,.4)
s.rect(220.5,209,5,3,fill='white',stroke=PURPLE,sw=.35)
s.num(225,202.5,10,r=2.6,size=2.8)
s.text(214,244.9,'XV-601 FC',2.1,600,'middle',mono=True)

# CP-801 on right rear/side post: 0.60 x 0.80, centre +1.50.
s.rect(205,164,24,32,fill='#EFF6F6',stroke=INK,sw=.5,rx=1)
s.rect(209,170,16,8,fill='white',stroke=MUTED,sw=.3)
s.text(217,175.2,'HMI',2.6,600,'middle',mono=True)
s.circle(210,184,1.5,fill='#C15B52',stroke=INK,sw=.3)
s.circle(216,184,1.1,fill=TEAL,stroke=INK,sw=.25)
s.circle(221.5,184,1.1,fill=AMBER,stroke=INK,sw=.25)
s.text(217,192,'CP-801',2.6,600,'middle',mono=True)
s.num(215,158.5,13,r=2.6,size=2.8)
s.line(229,180,232,180,INK,.6)
s.circle(217,180,.55,MUTED,'none')

# Pumps on tray, ahead of the treatment equipment.
pump(120,225,4,'P-102',tag_dy=10)
pump(163,225,11,'P-103',tag_dy=10)

# Folding service step is outside skid, its folded position shown in plan.
s.path('M125 231H195V232.6H125Z',MUTED,.4,'#CFDCE3')
s.line(128,232.6,126,240,MUTED,.45)
s.line(192,232.6,194,240,MUTED,.45)
s.text(160,248,'Fold-down service step (outside skid)',2.2,anchor='middle',fill=MUTED)

# Treated tank and pump on the right.
s.rect(256,194,64,46,fill='#F3EFF8',stroke=PURPLE,sw=.5,rx=3)
s.line(258,198,318,198,LINE,.3)
s.num(269,204,12,r=3.2,size=3.4)
s.text(289,211,'T-701',3.3,600,'middle',mono=True)
s.text(289,218,'2 m³',3.0,600,'middle')
s.text(288,224,'Short-term treated storage',2.5,anchor='middle')
pump(308,234,12,'P-104')

# Chamber below grade and below-grade lift pump.
s.rect(20,g,48,40,fill='#F4F6F7',stroke=MUTED,sw=.4,dash='2 1.3')
s.line(33,244,33,276,MUTED,.4,dash='1.5 1')
s.num(25,250,1,r=2.6,size=2.8)
s.text(46,251,'TR-101',2.5,600,'middle',mono=True)
s.text(49,257,'Collection',2.5,anchor='middle')
s.text(49,262,'chamber & trap',2.3,anchor='middle')
pump(53,271,2,'P-101')
s.text(92,276.5,'Below-ground chamber',2.2,anchor='middle',fill=MUTED)
s.text(92,280,'shown dashed',2.2,anchor='middle',fill=MUTED)

# Drain local assembly in front elevation with visible air-gap detail.
s.rect(255,250,12,5,fill='white',stroke=DRAIN,sw=.3)
s.num(260,245,15,r=2.6,size=2.8)
s.text(261,253.6,'DN50',2.0,600,'middle',mono=True)
s.line(261,255,261,257,DRAIN,.5,arrow='drain')
s.path('M258 259L259 261H263L264 259',DRAIN,.4)
s.text(249,261,'AG',2.1,600,mono=True)

# Elevation dimensions and callouts. Head top rounds to +1.96 m as specified.
dimv(8,160,240,12,12,'2.00')
dimv(72,240,280,68,68,'1.00')
dimv(238,152,240,232,232,'2.20')
dimv(247,141.6,240,195,232,'2.46')
dimv(198.5,141.6,161.56,195,192,'0.50 min')
dimv(324,194,240,320,320,'1.15')
s.text(148,166,'Head +1.96',2.1,fill=MUTED)
s.text(148,169,'0.22 head',2.1,fill=MUTED)
leader(112,237.9,102,234,90,232,'+0.09 support',2.1)
s.text(89,244.8,'GRADE ±0.00',2.1,600,fill=MUTED)

# Component key: identical full English names and identifiers on all sheets.
s.text(333,22,'COMPONENT KEY',3.0,600)
for i,(n,tag,name,fn) in enumerate(COMPONENTS):
    y=27.5+i*6.55
    s.num(336,y-.1,n,r=2.2,size=2.5)
    s.text(341,y-.5,tag,2.05,600,mono=True)
    s.text(341,y+2.55,name,2.08)

s.line(333,129.5,410,129.5,LINE,.3)
s.text(333,134,'EQUIPMENT DIMENSIONS · m',2.75,600)
specs=[
    'SK-901  3.00 × 1.40; 0.06 posts; 2.20 high',
    'Bearing level +0.09 above grade',
    'F-301  Ø0.406 × 1.651 shell (1665)',
    'F-302  Ø0.457 × 1.651 shell (1865)',
    'Valve heads 0.22 high; top +1.96',
    'F-303  Ø0.180 × 0.620',
    'UV-401 Ø0.089 × 0.950 long',
    'T-201  Ø1.90 × 2.00 (5 m³)',
    'T-701  1.60 × 1.20 × 1.15 (2 m³)',
    'TR-101 1.20 × 0.80 × 1.00 deep',
    'CP-801 0.60 × 0.80; centre +1.50',
    'Process piping DN32; drain piping DN50',
]
s.lines(333,139,specs,2.25,leading=3.35)
s.line(333,179,410,179,LINE,.3)
s.text(333,184,'DOCUMENTED CONSTRAINTS',2.75,600)
constraints=[
    '01 Service aisles are outside the skid.',
    '02 Heads at 1.96 m; use the folding step.',
    '03 Open above filters: no overhead beams.',
    '04 Corner/rear posts; CP on side/rear post.',
    '05 Cable tray stays behind the filters.',
    '06 Minimum clear site height: 2.50 m.',
    '    Indoors: verify equipment-room ceiling.',
    '    Outdoors: canopy >2.50 m or removable.',
    '07 Final dimensions require engineering.',
]
s.lines(333,189,constraints,2.25,leading=3.35)

# Outdoor site inset, deliberately NTS; baseline design remains the open frame.
s.text(333,222,'OUTDOOR SITE · NTS',2.75,600)
s.text(333,225.5,'Mecca sun: shade polyethylene tanks, pipes and electronics',2.0,fill=MUTED)
base=256; canopy=230; env=base-26*(2.46/2.80); head=base-26*(1.96/2.80)
s.line(333,base,409,base,INK,.35)
s.path(f'M333 {canopy}L404 {canopy}',INK,.8)
s.line(333.5,canopy,333.5,base,MUTED,.4)
s.line(403.5,canopy,403.5,base,MUTED,.4)
s.rect(336,237.5,14,18.5,fill='#EFF6F7',stroke=INK,sw=.3,rx=2)
s.text(343,247,'T-201',1.7,600,'middle',mono=True)
s.rect(354,base-20.4,1.2,20.4,fill='#D7E1E6',stroke=MUTED,sw=.2)
s.rect(381,base-20.4,1.2,20.4,fill='#D7E1E6',stroke=MUTED,sw=.2)
s.rect(357,env,21,head-env,fill='#EDF7F7',stroke=TEAL,sw=.25,dash='1.3 .8')
for x in [361,374]:
    s.rect(x-3,base-15.3,6,15.3,fill='#EAF4F3',stroke=INK,sw=.3,rx=2.5)
    s.rect(x-1.6,head,3.2,2.9,fill='white',stroke=INK,sw=.25)
s.rect(367,243,2.5,6,fill='#F1EEF7',stroke=PURPLE,sw=.25,rx=.6)
s.rect(386,246,14,10,fill='#F3EFF8',stroke=PURPLE,sw=.25,rx=1)
s.text(393,252,'T-701',1.7,600,'middle',mono=True)
s.text(367.5,236.3,'2.46 envelope',1.8,600,'middle',fill=TEAL)
s.text(368,229,'0.34 m clear above service envelope',1.8,600,'middle',fill=TEAL)
s.line(378,env,382,env,MUTED,.18)
s.raw(f'<path d="M381 {canopy}V{env}" fill="none" stroke="{MUTED}" stroke-width=".20" marker-start="url(#a-dim)" marker-end="url(#a-dim)"/>')
s.text(383,env+1.0,'0.34',1.8,600,fill=MUTED)
dimv(409,canopy,base,404,404,'2.80')
s.text(333,260,'Shade is above the 2.50 m minimum clear site height.',2.0,fill=MUTED)

# Explicitly non-baseline alternative, separately boxed under the main elevation.
s.rect(130,253,114,29,fill='#F8FAFB',stroke=LINE,sw=.3,rx=1)
s.text(133,257.5,'FUTURE LOW-CEILING OPTION · NOT THE BASELINE',2.55,600)
s.lines(133,262,[
    'Shorter, wider 54 in vessels, e.g. 1854 in place of 1665,',
    'may reduce valve-head top to approximately 1.68 m.',
    'Required service envelope would be about 2.18 m,',
    'within a closed 2.20 m frame. Engineering review required.',
    'Current drawing retains the specified 1665 / 1865 vessels.',
],2.35,leading=3.6)

titleblock(s,2,'M20 general arrangement — plan, elevation and site','1:25',y=264)
s.text(272,286,'Print A3 at 100% • do not scale a fitted-page print',2.15,fill=MUTED)
s.save('sheet-2-ga.svg')

