// Screen-space annotation layout only; no process or telemetry calculations.
const clamp=(v,low,high)=>Math.max(low,Math.min(high,v));
export const overviewDistance=aspect=>19.5/Math.min(1,Math.max(.35,aspect)/1.45);
const overlaps=(a,b,gap)=>a.left<b.left+b.width+gap&&a.left+a.width+gap>b.left&&a.top<b.top+b.height+gap&&a.top+a.height+gap>b.top;

export function layoutLabels(items,width,height,{padding=9,gap=8}={}) {
  const placed=[];
  for(const item of items){
    const maxX=Math.max(padding,width-padding-item.width),maxY=Math.max(padding,height-padding-item.height);
    const preferred={left:clamp(item.x-item.width/2,padding,maxX),top:clamp(item.y-item.height-10,padding,maxY)};
    const xs=[preferred.left,padding,maxX],ys=[preferred.top,padding,maxY];
    for(const prior of placed){xs.push(prior.left-item.width-gap,prior.left+prior.width+gap);ys.push(prior.top-item.height-gap,prior.top+prior.height+gap);}
    let best=null,bestCost=Infinity;
    for(const x of xs)for(const y of ys){
      const box={left:clamp(x,padding,maxX),top:clamp(y,padding,maxY),width:item.width,height:item.height};
      if(placed.some(prior=>overlaps(box,prior,gap)))continue;
      const dx=box.left-preferred.left,dy=box.top-preferred.top,cost=dx*dx+dy*dy*(dy>0?1.2:1);
      if(cost<bestCost){best=box;bestCost=cost;}
    }
    // Normal viewports have ample room for six labels. Keep full text present
    // even in an exceptionally tiny viewport, rather than truncate information.
    best??={...preferred,width:item.width,height:item.height};
    const right=best.left+best.width,bottom=best.top+best.height;
    const leader={x:clamp(item.x,best.left+4,right-4),y:clamp(item.y,best.top+4,bottom-4)};
    if(item.y>=bottom)leader.y=bottom;else if(item.y<=best.top)leader.y=best.top;
    else if(item.x<best.left)leader.x=best.left;else if(item.x>right)leader.x=right;
    placed.push({...best,id:item.id,anchor:{x:item.x,y:item.y},leader});
  }
  return placed;
}
