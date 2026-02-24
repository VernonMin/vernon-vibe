const summaryCards = document.querySelector('#summaryCards');
const serviceTable = document.querySelector('#serviceTable');
const traceTable = document.querySelector('#traceTable');
const logTable = document.querySelector('#logTable');
const canvas = document.querySelector('#metricCanvas');
const ctx = canvas.getContext('2d');

const fmt = (ts) => new Date(ts * 1000).toLocaleString('zh-CN');

function table(headers, rows) {
  return `\n<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>\n<tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody>`;
}

function drawMetric(series) {
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if (!series.length) return;
  const values = series.map(s => s.avg_value);
  const min = Math.min(...values) - 2;
  const max = Math.max(...values) + 2;
  ctx.strokeStyle = '#22d3ee';
  ctx.lineWidth = 2;
  ctx.beginPath();
  series.forEach((p, i) => {
    const x = (i / (series.length - 1 || 1)) * (canvas.width - 40) + 20;
    const y = canvas.height - ((p.avg_value - min) / (max - min || 1)) * (canvas.height - 30) - 10;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function refresh() {
  const overview = await fetch('/api/overview?minutes=120').then(r => r.json());
  const metric = await fetch('/api/metrics?name=request_per_second&minutes=120').then(r => r.json());

  summaryCards.innerHTML = ['logs','metrics','traces'].map(k =>
    `<div class="card"><h3>${k.toUpperCase()}</h3><p>${overview.counts[k]}</p></div>`
  ).join('');

  serviceTable.innerHTML = table(['Service', 'Events'], overview.top_services.map(x => [x.service, x.events]));
  traceTable.innerHTML = table(['Service', 'Avg(ms)', 'Max(ms)', 'Spans'], overview.trace_stats.map(x => [x.service, Number(x.avg_duration).toFixed(1), Number(x.max_duration).toFixed(1), x.span_count]));
  logTable.innerHTML = table(['Time', 'Service', 'Level', 'Message'], overview.recent_logs.map(x => [fmt(x.timestamp), x.service, x.level, x.message]));

  drawMetric(metric.series);
}

document.querySelector('#seedBtn').addEventListener('click', async () => {
  await fetch('/demo/generate', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ service: 'checkout' })});
  await refresh();
});

document.querySelector('#refreshBtn').addEventListener('click', refresh);
refresh();
