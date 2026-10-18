// Educational stage identities only. These lists never determine plant state,
// flow, treatment effectiveness, inventory, or a water parcel's residence time.
const stage=(equipment,pipes,labels)=>Object.freeze({equipment:Object.freeze(equipment),pipes:Object.freeze(pipes),labels:Object.freeze(labels)});
export const WATER_JOURNEY=Object.freeze({
  collection:stage(['inlet','strainer','raw','feed','flow_meter'],['collection','screen-to-raw','raw-to-feed'],['raw']),
  media:stage(['dose_pre','media'],['feed-to-media'],['media']),
  carbon:stage(['dose_dechlor','orp','carbon'],['media-to-carbon'],['carbon']),
  polish:stage(['cartridge','dose_ph','dose_final'],['carbon-to-cartridge','cartridge-to-compliance'],['cartridge']),
  verify:stage(['quality','compliance'],['cartridge-to-compliance'],['quality','compliance']),
  uv:stage(['uv'],['compliance-to-uv'],['uv']),
  storage:stage(['treated'],['product-to-storage'],['treated']),
  irrigation:stage(['reuse','valve'],['storage-to-reuse','reuse-to-valve','irrigation-out'],['valve']),
});
export const isJourneyStage=id=>typeof id==='string'&&Object.hasOwn(WATER_JOURNEY,id);
export const journeyStage=id=>isJourneyStage(id)?WATER_JOURNEY[id]:null;
