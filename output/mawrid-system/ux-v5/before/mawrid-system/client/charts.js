const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const number = value => new Intl.NumberFormat('en-US', { maximumFractionDigits: 3 }).format(value);

/* A missing measurement breaks the path. No interpolation or synthetic values. */
export function sensorChart(rows, channel) {
  const points = rows.map((row, index) => ({ index, value: row.channels?.[channel.key], row }));
  const finite = points.filter(point => typeof point.value === 'number' && Number.isFinite(point.value));
  if (!finite.length) return { svg: '', finiteCount: 0, missingCount: rows.length, min: null, max: null, latest: null };
  const width = 760, height = 245, left = 52, right = 20, top = 23, bottom = 32;
  const rawMin = Math.min(...finite.map(p => p.value)), rawMax = Math.max(...finite.map(p => p.value));
  const range = rawMax - rawMin, padding = range ? range * 0.14 : Math.max(Math.abs(rawMin) * 0.03, 0.05);
  const min = rawMin - padding, max = rawMax + padding;
  const x = index => left + (rows.length < 2 ? 0.5 : index / (rows.length - 1)) * (width - left - right);
  const y = value => top + (max - value) / (max - min) * (height - top - bottom);
  let drawing = false, path = '';
  points.forEach(point => {
    if (typeof point.value !== 'number' || !Number.isFinite(point.value)) { drawing = false; return; }
    path += `${drawing ? 'L' : 'M'}${x(point.index).toFixed(2)},${y(point.value).toFixed(2)} `; drawing = true;
  });
  const grid = Array.from({ length: 4 }, (_, index) => {
    const value = min + ((max - min) * index / 3), yy = y(value);
    return `<line class="chart-grid" x1="${left}" y1="${yy}" x2="${width - right}" y2="${yy}"/><text class="chart-axis" x="${left - 10}" y="${yy + 3}" text-anchor="end">${esc(number(value))}</text>`;
  }).join('');
  const indices = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
  const labels = indices.map(index => `<text class="chart-axis" x="${x(index)}" y="${height - 7}" text-anchor="${index === 0 ? 'start' : index === rows.length - 1 ? 'end' : 'middle'}">${esc(String(rows[index]?.timestamp || '').replace('T', ' ').slice(11, 19) || `#${rows[index]?.sample_index ?? index}`)}</text>`).join('');
  const dots = finite.filter(p => p.row.prediction === 1 || finite.length === 1).map(p => `<circle cx="${x(p.index)}" cy="${y(p.value)}" r="${p.row.prediction === 1 ? 3.5 : 3}" fill="${p.row.prediction === 1 ? '#bb7966' : '#547f52'}"><title>${esc(`${channel.name}: ${number(p.value)} ${channel.unit || ''} · ${p.row.timestamp || ''}${p.row.prediction === 1 ? ' · إشارة شذوذ' : ''}`)}</title></circle>`).join('');
  const svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(`قراءات ${channel.name}، ${finite.length} قراءة متوفرة من ${rows.length}؛ الأقل ${number(rawMin)} والأعلى ${number(rawMax)}.`)}" xmlns="http://www.w3.org/2000/svg">${grid}<path class="chart-line" d="${path}"/>${dots}${labels}</svg>`;
  return { svg, finiteCount: finite.length, missingCount: rows.length - finite.length, min: rawMin, max: rawMax, latest: finite.at(-1).value };
}
