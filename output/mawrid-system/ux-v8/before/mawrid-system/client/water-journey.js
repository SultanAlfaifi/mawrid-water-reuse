// Ordered explanation of the proposed process. Stage changes never advance
// plant time, integrate water, authorize reuse or issue a control command.
export const WATER_JOURNEY = [
  {id:'collection',short:'التجميع',title:'نجمع الماء قبل معالجته',role:'تصل مياه الوضوء والمغاسل عبر المصفاة إلى خزان التجميع، ثم تسحبها المضخة.',benefit:'حجز الشوائب الكبيرة وتوفير مخزون يغذّي خط المعالجة.'},
  {id:'media',short:'مرشح الوسائط',title:'نحجز العوالق',role:'يمر الماء بنقطة الجرعة الأولية ثم مرشح الوسائط الذي يحجز العوالق.',benefit:'تخفيف حمل الجسيمات على المراحل التالية.'},
  {id:'carbon',short:'مرشح الكربون',title:'يمر الماء عبر الكربون',role:'تسبق الكربون وحدة إزالة الكلور ونقطة متابعة، ثم يمر الماء عبر الكربون التجاري.',benefit:'إضافة معالجة لبعض المواد التي لا يحجزها الترشيح وحده.'},
  {id:'polish',short:'الترشيح الدقيق',title:'نستكمل تجهيز الماء',role:'يعبر الماء مرشح الخراطيش، ثم نقطتي الإضافة لضبط الماء والكلورة النهائية.',benefit:'ترشيح إضافي وتجهيز الماء للفحص قبل التخزين.'},
  {id:'verify',short:'التحقق',title:'نقرأ المؤشرات قبل التمرير',role:'تعرض لوحة التحليل مؤشرات الماء، ويحدد صمام المطابقة مساره في التصميم.',benefit:'ربط القياس بالقرار. عند الاحتجاز توقف المحاكاة التدفق؛ لا تحسب إعادة الماء للخام.'},
  {id:'uv',short:'التعقيم الإضافي',title:'حاجز تعقيم إضافي اختياري',role:'يتضمن التصميم موضعًا للأشعة فوق البنفسجية قبل خزان المنتج.',benefit:'إضافة حاجز تعقيم محتمل؛ فعاليته تحتاج اختبارًا فعليًا.'},
  {id:'storage',short:'خزان المنتج',title:'نخزن الماء بعد المعالجة',role:'يستقبل الخزان الأفقي الماء بعد خط المعالجة، ويظهر مخزونه في المحاكاة.',benefit:'فصل وقت إنتاج الماء عن وقت استخدامه للري.'},
  {id:'irrigation',short:'الري',title:'نصل إلى الري',role:'تنقل المضخة الماء من الخزان إلى مسار الري عندما تسمح قواعد المحاكاة.',benefit:'متابعة كمية الماء الخارجة للري. جرّب الآن ما يحدث عند انقطاع الحساس.'},
];
export function journeyProgress(ui={},sessionId){
  const same=typeof sessionId==='string'&&ui.journeySession===sessionId;
  const index=same&&Number.isInteger(ui.journeyIndex)?Math.max(0,Math.min(WATER_JOURNEY.length-1,ui.journeyIndex)):0;
  return {index,total:WATER_JOURNEY.length,stage:WATER_JOURNEY[index],complete:same&&ui.journeyComplete===true};
}
