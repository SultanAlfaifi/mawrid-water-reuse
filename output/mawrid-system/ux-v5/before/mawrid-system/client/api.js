/* Same-origin local API. Errors are visible; no generated-data fallback. */
export class ApiError extends Error {
  constructor(message, code = 'request_failed', status = 0) {
    super(message); this.name = 'ApiError'; this.code = code; this.status = status;
  }
}

async function request(path, { method = 'GET', body, timeout = 120000, binary = false } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {
      method, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: { Accept: binary ? 'text/csv,application/octet-stream,application/json' : 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) {
      let payload; try { payload = await response.json(); } catch { /* Preserve HTTP failure. */ }
      throw new ApiError(payload?.error?.message || `تعذّر تنفيذ الطلب (HTTP ${response.status}).`, payload?.error?.code, response.status);
    }
    if (binary) return await response.blob();
    try { return await response.json(); }
    catch { throw new ApiError('وصل رد غير صالح من الخدمة المحلية.', 'invalid_response', response.status); }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error.name === 'AbortError') throw new ApiError('استغرق الطلب وقتًا طويلًا. حدّث الحالة للتأكد مما اكتمل قبل تكراره.', 'timeout');
    throw new ApiError('تعذّر الوصول إلى الخدمة المحلية. تأكد من تشغيل خادم مورد ثم أعد المحاولة.', 'network_error');
  } finally { clearTimeout(timer); }
}

export const api = {
  state: () => request('/api/state', { timeout: 30000 }),
  sources: () => request('/api/sources', { timeout: 30000 }),
  createSession: (sourceId, researchAck) => request('/api/sessions', { method: 'POST', body: { source_id: sourceId, research_ack: researchAck } }),
  step: count => request('/api/replay/step', { method: 'POST', body: { count } }),
  pause: () => request('/api/replay/pause', { method: 'POST', body: {} }),
  plantControl: control => request('/api/plant/control', { method: 'POST', body: control }),
  stop: () => request('/api/control/stop', { method: 'POST', body: { note: 'احتجاز يدوي من واجهة مورد المحلية' } }),
  reset: () => request('/api/control/reset', { method: 'POST', body: {} }),
  acknowledge: id => request(`/api/alarms/${encodeURIComponent(id)}/ack`, { method: 'POST', body: { note: 'تمت المراجعة من واجهة مورد المحلية' } }),
  readings: ({ limit = 100, sessionId } = {}) => request(`/api/readings?${new URLSearchParams({ limit: String(limit), ...(sessionId ? { session_id: sessionId } : {}) })}`),
  alarms: () => request('/api/alarms?limit=100'),
  settings: () => request('/api/settings'),
  saveSettings: settings => request('/api/settings', { method: 'PATCH', body: settings }),
  report: () => request('/api/report'),
  export: type => request(`/api/export/${type === 'events' ? 'events' : 'readings'}.csv`, { binary: true }),
};

export function safeLink(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value, location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}
