import { WATER_JOURNEY } from './water-journey.js';
// Presentation time is independent of the virtual plant clock. No network,
// plant controls or automatic fault injection belongs in this module.
export function readingDuration(stage){
  const words=[stage?.title,stage?.role,stage?.benefit].filter(Boolean).join(' ').trim().split(/\s+/).filter(Boolean).length;
  return Math.max(20000,Math.min(30000,Math.ceil(words/1.35+6)*1000));
}
export const PRESENTATION_DURATION=WATER_JOURNEY.reduce((sum,stage)=>sum+readingDuration(stage),0);
export class JourneyPresentation {
  constructor(){this.stop();}
  stop(){this.status='idle';this.sessionId=null;this.index=0;this.remainingMs=0;this.durationMs=0;this.waitingCamera=false;this.lastAt=null;this.waitingSince=null;this.reason='';}
  start(sessionId,now){if(typeof sessionId!=='string'||!sessionId)throw new Error('A virtual session is required');this.sessionId=sessionId;this.index=0;this.status='playing';this.reason='';this.prepare(now);}
  prepare(now){this.durationMs=readingDuration(WATER_JOURNEY[this.index]);this.remainingMs=this.durationMs;this.waitingCamera=true;this.lastAt=null;this.waitingSince=now;}
  settle(id,now){if(this.status!=='playing'||!this.waitingCamera||WATER_JOURNEY[this.index].id!==id)return false;this.waitingCamera=false;this.lastAt=now;this.waitingSince=null;return true;}
  consume(now){if(this.status==='playing'&&!this.waitingCamera&&this.lastAt!==null){this.remainingMs=Math.max(0,this.remainingMs-Math.max(0,now-this.lastAt));this.lastAt=Math.max(now,this.lastAt);}}
  tick(now){
    this.consume(now);if(this.status!=='playing'||this.waitingCamera||this.remainingMs>0)return false;
    if(this.index===WATER_JOURNEY.length-1){this.status='complete';this.lastAt=null;this.reason='';return true;}
    this.index++;this.prepare(now);return true;
  }
  pause(reason,now){if(this.status!=='playing')return false;this.consume(now);this.status='paused';this.reason=reason;this.lastAt=null;return true;}
  resume(now){if(this.status!=='paused')return false;this.status='playing';this.reason='';this.waitingCamera=true;this.waitingSince=now;this.lastAt=null;return true;}
  view(){return {status:this.status,sessionId:this.sessionId,index:this.index,remainingMs:this.remainingMs,durationMs:this.durationMs,waitingCamera:this.waitingCamera,reason:this.reason};}
}
