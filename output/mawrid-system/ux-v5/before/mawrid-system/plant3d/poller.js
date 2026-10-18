import { adaptState } from './adapter.js';
/* One GET in flight. No endpoint/action selection or simulation clock here. */
export class StatePoller {
  constructor({fetchState=options=>fetch('/api/state',options),onState=()=>{},now=()=>performance.now(),
    schedule=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id),intervalMs=2000,timeoutMs=4500}={}) {
    Object.assign(this,{fetchState,onState,now,schedule,cancel,intervalMs,timeoutMs});
    this.state={connection:'connecting',snapshot:null,lastSuccessAt:null,error:null,reset:true};
    this.active=false;this.generation=0;this.inFlight=false;this.timer=null;this.controller=null;
  }
  emit(patch){this.state={...this.state,...patch};this.onState(this.state);}
  start(){if(this.active)return;this.active=true;this.generation++;this.emit({connection:'connecting'});if(!this.inFlight)this.poll();}
  stop(){this.active=false;this.generation++;if(this.timer!==null)this.cancel(this.timer);this.timer=null;this.controller?.abort();this.emit({connection:'disconnected',error:'توقفت متابعة الاتصال.',reset:false});}
  async poll(){
    if(!this.active||this.inFlight)return false;
    if(this.timer!==null)this.cancel(this.timer);this.timer=null;
    this.inFlight=true;const generation=this.generation,controller=new AbortController();this.controller=controller;let expired=false;
    const current=()=>this.active&&generation===this.generation&&!expired;
    const deadline=this.schedule(()=>{
      if(!current())return;expired=true;controller.abort();
      this.emit({connection:'disconnected',error:'تعذر تحديث الحالة؛ المعروض آخر لقطة مستلمة.',reset:false});
    },this.timeoutMs);
    try {
      const response=await this.fetchState({method:'GET',cache:'no-store',credentials:'same-origin',signal:controller.signal,headers:{Accept:'application/json'}});
      if(!current())return false;
      if(!response.ok)throw new Error('استجابة الخادم غير متاحة.');
      const data=await response.json();if(!current())return false;
      const snapshot=adaptState(data),reset=this.state.snapshot?.sessionId!==snapshot?.sessionId;
      this.emit({connection:'connected',snapshot,lastSuccessAt:this.now(),error:null,reset});
      return true;
    } catch(error) {
      if(current())this.emit({connection:'disconnected',error:'تعذر تحديث الحالة؛ المعروض آخر لقطة مستلمة.',reset:false});
      return false;
    } finally {
      this.cancel(deadline);this.inFlight=false;if(this.controller===controller)this.controller=null;
      if(this.active)this.timer=this.schedule(()=>this.poll(),this.intervalMs);
    }
  }
}
