/* AlphaStream Workbench — 前端逻辑
 *
 * 设计要点：屏幕上任何数字都必须来自某个具体的 Run。切换 Run 时，
 * 徽章（evidence）、校准、风险三个视图一起重算，避免出现"数字与出处不一致"。
 */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = { runs: [], current: null, poll: null };

/* ------------------------------- helpers ------------------------------- */

async function api(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
  return data;
}

const pct = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : (v * 100).toFixed(d) + '%';
const num = (v, d = 3) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(d);
const esc = (s) =>
  String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const AXIS = { gridcolor: '#23304a', zerolinecolor: '#2c3b58', color: '#8698b5' };
const CONFIG = { displayModeBar: false, responsive: true };
function layout(extra = {}) {
  return Object.assign(
    {
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#c9d6e8', size: 11 },
      margin: { l: 62, r: 20, t: 26, b: 44 },
      xaxis: Object.assign({}, AXIS),
      yaxis: Object.assign({}, AXIS),
      showlegend: true,
      legend: { orientation: 'h', y: 1.14, x: 0, font: { size: 11 } },
      hovermode: 'closest',
    },
    extra
  );
}
function draw(id, traces, extra) {
  Plotly.react(id, traces, layout(extra), CONFIG);
}
function empty(id, text) {
  Plotly.react(id, [], layout({
    annotations: [{ text, showarrow: false, font: { color: '#8698b5', size: 12 },
                    xref: 'paper', yref: 'paper', x: .5, y: .5 }],
    xaxis: { visible: false }, yaxis: { visible: false }, showlegend: false,
  }), CONFIG);
}

/* --------------------------------- tabs -------------------------------- */

$$('.tabs button').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.tabs button').forEach((b) => b.classList.remove('active'));
    $$('.tab-panel').forEach((p) => p.classList.remove('active'));
    btn.classList.add('active');
    $('#tab-' + btn.dataset.tab).classList.add('active');
    window.dispatchEvent(new Event('resize'));
  });
});

/* --------------------------------- runs -------------------------------- */

async function loadRuns(selectId) {
  const { runs } = await api('/api/runs');
  state.runs = runs;
  const select = $('#run-select');
  select.innerHTML = runs
    .map((r) => `<option value="${esc(r.run_id)}">${esc(r.run_id)}${r.label ? ' · ' + esc(r.label) : ''}</option>`)
    .join('');
  $('#runs-count').textContent = `（${runs.length}）`;

  const tbody = $('#runs-table tbody');
  tbody.innerHTML = runs
    .map(
      (r) => `<tr data-run="${esc(r.run_id)}">
        <td class="mono">${esc(r.run_id)}</td>
        <td><span class="pill ${esc(r.state)}">${esc(r.state)}</span></td>
        <td class="num">${r.median_rel_error != null ? pct(r.median_rel_error) : '—'}</td>
        <td class="num">${r.effective_dates ?? '—'}</td>
        <td class="mono">${r.parameters ? `w=${r.parameters.window} mh=${r.parameters.min_history} D=${r.parameters.specific_shrinkage}` : '—'}</td>
      </tr>`
    )
    .join('');
  $$('#runs-table tbody tr').forEach((tr) =>
    tr.addEventListener('click', () => selectRun(tr.dataset.run))
  );

  const left = $('#compare-left');
  const right = $('#compare-right');
  if (left && right) {
    const options = runs.map((r) => `<option value="${esc(r.run_id)}">${esc(r.run_id)}</option>`).join('');
    left.innerHTML = options;
    right.innerHTML = options;
    if (runs.length > 1) right.selectedIndex = 1;
  }

  const target = selectId || state.current || (runs[0] && runs[0].run_id);
  if (target && runs.some((r) => r.run_id === target)) {
    select.value = target;
    await selectRun(target, { keepList: true });
  }
}

async function selectRun(runId, opts = {}) {
  state.current = runId;
  $('#run-select').value = runId;
  $$('#runs-table tbody tr').forEach((tr) =>
    tr.classList.toggle('selected', tr.dataset.run === runId)
  );

  const detail = await api(`/api/runs/${runId}`);
  renderDetail(detail);
  try {
    const { badges } = await api(`/api/runs/${runId}/evidence`);
    renderBadges(badges);
  } catch (err) {
    $('#badges').innerHTML = `<div class="badge danger"><div class="t">无法生成证据徽章</div><div class="d">${esc(err.message)}</div></div>`;
  }
  await loadCalibration(runId);
  await loadRisk(runId);
  if (!opts.keepList) await loadRuns(runId);
}

function renderDetail({ summary, manifest, status }) {
  const el = $('#run-detail');
  if (!manifest) {
    el.innerHTML = `<h2>${esc(summary.run_id)}</h2>
      <p class="muted">该 run 还没有 manifest（state: ${esc(summary.state)}）。</p>
      ${status && status.command ? `<dl class="kv"><dt>命令</dt><dd>${esc(status.command.join(' '))}</dd></dl>` : ''}
      <h2 style="margin-top:14px">运行日志</h2><pre class="log" id="run-log">加载中…</pre>`;
    api(`/api/runs/${summary.run_id}/log?lines=40`)
      .then((d) => { $('#run-log').textContent = d.lines.join('\n') || '(空)'; })
      .catch(() => { $('#run-log').textContent = '(无日志)'; });
    return;
  }
  const p = manifest.parameters || {};
  const sc = manifest.selfcheck || {};
  const checks = manifest.checks || {};
  const inputs = manifest.inputs || {};
  const rows = [
    ['run_id', manifest.label ? `${summary.run_id}  ·  ${manifest.label}` : summary.run_id],
    ['生成时间 (UTC)', manifest.generated_utc],
    ['git rev', manifest.git_rev],
    ['参数', `window=${p.window} · min_history=${p.min_history} · D=${p.specific_shrinkage} · F=${p.factor_shrinkage}`],
    ['依赖版本', Object.entries(manifest.versions || {}).map(([k, v]) => `${k}=${v}`).join(' · ')],
    ['X 输入', inputs.exposures ? `${inputs.exposures.path} (${Number(inputs.exposures.size_bytes).toLocaleString()} B @ ${inputs.exposures.modified_utc})` : '—'],
    ['收益输入', inputs.returns ? `${inputs.returns.path} (${Number(inputs.returns.size_bytes).toLocaleString()} B @ ${inputs.returns.modified_utc})` : '—'],
    ['形状', Object.entries(manifest.shapes || {}).map(([k, v]) => `${k}=[${v}]`).join(' · ')],
    ['检查', `F PD=${checks.F_positive_definite} · D 全正=${checks.D_all_positive} · Σ PD=${checks.Sigma_positive_definite}`],
    ['self-check', `${sc.effective_dates} 天 · median ${pct(sc.rel_error_median)} · mean ${pct(sc.rel_error_mean)}`],
  ];
  el.innerHTML = `<h2>Manifest</h2><dl class="kv">${rows
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v ?? '—')}</dd>`)
    .join('')}</dl>
    <h2 style="margin-top:16px">产物</h2>
    <p><a class="pill" href="/api/runs/${encodeURIComponent(summary.run_id)}/artifact/run_manifest.json">⬇ run_manifest.json（对账用，可直接发给协作者）</a>
      ${(summary.artifacts || [])
      .map((a) => `<a class="pill" href="/api/runs/${encodeURIComponent(summary.run_id)}/artifact/${encodeURIComponent(a)}">${esc(a)}</a>`)
      .join(' ')}</p>`;
}

function renderBadges(badges) {
  $('#badges').innerHTML = badges
    .map(
      (b) => `<div class="badge ${esc(b.level)}" title="${esc(b.detail)}">
        <div class="t">${esc(b.title)}</div><div class="d">${esc(b.detail)}</div></div>`
    )
    .join('');
}

/* ------------------------------ calibration ---------------------------- */

async function loadCalibration(runId) {
  let data;
  try {
    data = await api(`/api/runs/${runId}/calibration`);
  } catch (err) {
    $('#cal-tiles').innerHTML = `<div class="tile danger"><div class="k">校准</div><div class="v">不可用</div><div class="n">${esc(err.message)}</div></div>`;
    ['#cal-series', '#cal-hist', '#cal-quarter', '#cal-vs'].forEach((id) => empty(id, '无自检报告'));
    return;
  }
  const s = data.summary;
  $('#cal-tiles').innerHTML = [
    ['检验天数', String(s.effective_dates), `${s.first_date} → ${s.last_date}`, ''],
    ['相对误差中位数', pct(s.median), `IQR ${pct(s.p25, 1)} – ${pct(s.p75, 1)}`, s.median > 0.2 ? 'warn' : ''],
    ['平均相对误差', pct(s.mean), `最好 ${pct(s.best, 1)} / 最差 ${pct(s.worst, 1)}`, ''],
    ['该数字的用途', '样本内诊断', '不是样本外预测误差', 'danger'],
  ]
    .map(([k, v, n, cls]) => `<div class="tile ${cls}"><div class="k">${k}</div><div class="v">${v}</div><div class="n">${esc(n)}</div></div>`)
    .join('');

  const series = data.series;
  draw('#cal-series', [
    { x: series.dates, y: series.rel_error, mode: 'markers', name: '当日相对误差',
      marker: { size: 4, color: 'rgba(77,163,255,.55)' } },
    { x: series.dates, y: series.rolling_median, mode: 'lines', name: '20 日滚动中位数',
      line: { color: '#f5b544', width: 2 } },
  ], { yaxis: Object.assign({}, AXIS, { tickformat: '.0%', title: '相对误差' }) });

  draw('#cal-hist', [
    { x: data.histogram.edges.slice(0, -1), y: data.histogram.counts, type: 'bar',
      marker: { color: 'rgba(77,163,255,.6)' }, name: '天数' },
  ], { xaxis: Object.assign({}, AXIS, { tickformat: '.0%', title: '相对误差' }),
       yaxis: Object.assign({}, AXIS, { title: '天数' }), showlegend: false, bargap: 0.05 });

  draw('#cal-quarter', [
    { x: data.quarterly.map((q) => q.period), y: data.quarterly.map((q) => q.median),
      type: 'bar', marker: { color: 'rgba(53,208,127,.65)' }, name: '中位数',
      text: data.quarterly.map((q) => `${q.days}天`), textposition: 'outside',
      textfont: { size: 10, color: '#8698b5' } },
  ], { yaxis: Object.assign({}, AXIS, { tickformat: '.0%', title: '相对误差中位数' }),
       xaxis: Object.assign({}, AXIS, { title: '' }), showlegend: false });

  const lo = Math.min(...series.realized_vol), hi = Math.max(...series.model_vol);
  draw('#cal-vs', [
    { x: [lo, hi], y: [lo, hi], mode: 'lines', name: 'y = x（完美预测）',
      line: { color: '#8698b5', dash: 'dash', width: 1 } },
    { x: series.realized_vol, y: series.model_vol, mode: 'markers', name: '检验日',
      marker: { size: 5, color: 'rgba(77,163,255,.6)' } },
  ], { xaxis: Object.assign({}, AXIS, { tickformat: '.0%', title: '已实现波动率（截面均值）' }),
       yaxis: Object.assign({}, AXIS, { tickformat: '.0%', title: '模型波动率（截面均值）' }) });
}

/* --------------------------------- risk -------------------------------- */

async function loadRisk(runId, scheme) {
  const chosen = scheme || $('#scheme-select').value || 'equal';
  let data;
  try {
    data = await api(`/api/runs/${runId}/risk?scheme=${encodeURIComponent(chosen)}`);
  } catch (err) {
    $('#risk-tiles').innerHTML = `<div class="tile danger"><div class="k">风险透视</div><div class="v">不可用</div><div class="n">${esc(err.message)}</div></div>`;
    ['#risk-exposure', '#risk-contrib', '#risk-voldist'].forEach((id) => empty(id, '缺少产物'));
    $('#scheme-table tbody').innerHTML = '';
    return;
  }
  const p = data.portfolio;
  const lowVol = p.vol_annualized < 0.05;
  const cond = data.conditioning || {};
  const illConditioned = (cond.condition_number || 0) > 500;
  $('#risk-tiles').innerHTML = [
    ['组合年化波动', pct(p.vol_annualized), lowVol ? '⚠️ 低于 5%，疑似缺市场因子' : data.scheme_label,
     lowVol ? 'danger' : ''],
    ['因子 / 特异 方差占比', `${pct(p.factor_pct, 1)} / ${pct(p.specific_pct, 1)}`, `截至 ${data.as_of}`, ''],
    ['有效持仓数 1/Σw²', num(p.effective_n, 1), `最大权重 ${pct(p.max_weight, 1)} · 股票数 ${data.universe}`, ''],
    ['Σ 条件数 λmax/λmin', (cond.condition_number || 0).toExponential(2),
     illConditioned ? '⚠️ 病态：最小方差解对 Σ 的估计误差极敏感' : '最小方差解相对稳定',
     illConditioned ? 'warn' : ''],
    ['权重方案', data.scheme_label, '同一份 Σ，不同目标函数', ''],
  ]
    .map(([k, v, n, cls]) => `<div class="tile ${cls}"><div class="k">${k}</div><div class="v">${v}</div><div class="n">${esc(n)}</div></div>`)
    .join('');

  const factors = data.factors.slice().reverse();
  draw('#risk-exposure', [
    { y: factors.map((f) => f.factor), x: factors.map((f) => f.exposure), type: 'bar',
      orientation: 'h', marker: { color: 'rgba(77,163,255,.65)' }, name: '暴露' },
  ], { xaxis: Object.assign({}, AXIS, { title: 'X′w（横截面 z-score 单位）' }),
       showlegend: false, margin: { l: 110, r: 20, t: 16, b: 44 } });

  draw('#risk-contrib', [
    { y: factors.map((f) => f.factor), x: factors.map((f) => f.vol_contribution), type: 'bar',
      orientation: 'h', marker: { color: 'rgba(245,181,68,.7)' }, name: '年化波动贡献' },
  ], { xaxis: Object.assign({}, AXIS, { tickformat: '.1%', title: '年化波动贡献 √(bₖ(Fb)ₖ·252)' }),
       showlegend: false, margin: { l: 110, r: 20, t: 16, b: 44 } });

  draw('#risk-voldist', [
    { x: data.model_vol_distribution.edges.slice(0, -1), y: data.model_vol_distribution.counts,
      type: 'bar', marker: { color: 'rgba(53,208,127,.6)' }, name: '股票数' },
  ], { xaxis: Object.assign({}, AXIS, { tickformat: '.0%', title: '个股模型年化波动率' }),
       yaxis: Object.assign({}, AXIS, { title: '股票数' }), showlegend: false, bargap: 0.05 });

  $('#scheme-table tbody').innerHTML = data.schemes
    .map(
      (s) => `<tr${s.scheme === chosen ? ' class="selected"' : ''}>
        <td>${esc(s.label)}</td>
        <td class="num">${pct(s.vol_annualized)}</td>
        <td class="num">${num(s.effective_n, 1)}</td>
        <td class="num">${pct(s.max_weight, 1)}</td>
      </tr>`
    )
    .join('');
}

$('#scheme-select').addEventListener('change', () => {
  if (state.current) loadRisk(state.current, $('#scheme-select').value);
});

/* -------------------------------- compare ------------------------------ */

$('#compare-run').addEventListener('click', async () => {
  const left = $('#compare-left').value;
  const right = $('#compare-right').value;
  const box = $('#compare-result');
  if (left === right) {
    box.innerHTML = '<div class="card"><p class="muted">请选择两个不同的 Run。</p></div>';
    return;
  }
  box.innerHTML = '<div class="card"><p class="muted">对账中…</p></div>';
  let data;
  try {
    data = await api(`/api/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`);
  } catch (err) {
    box.innerHTML = `<div class="card"><p class="muted">对账失败：${esc(err.message)}</p></div>`;
    return;
  }
  const table = (title, rows, sub) => {
    const changed = rows.filter((r) => r.changed).length;
    return `<div class="card"><h2>${title} <span class="muted">${changed} 项不同</span></h2>
      ${sub ? `<p class="sub">${sub}</p>` : ''}
      <div class="table-wrap"><table><thead><tr><th>字段</th>
        <th>A · ${esc(left)}</th><th>B · ${esc(right)}</th></tr></thead><tbody>
      ${rows.map((r) => `<tr><td class="${r.changed ? 'changed' : 'same'}">${esc(r.field)}</td>
        <td class="mono">${esc(fmtVal(r.left))}</td>
        <td class="mono">${esc(fmtVal(r.right))}</td></tr>`).join('')}
      </tbody></table></div></div>`;
  };
  const fmtVal = (v) => {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'number') return Math.abs(v) < 1 && v !== 0 ? v.toExponential(4) : String(v);
    return Array.isArray(v) ? `[${v}]` : String(v);
  };

  box.innerHTML =
    table('参数', data.parameters, '参数不同 → 两边跑的不是同一套配置。') +
    table('形状', data.shapes, 'X / 因子数 / 股票数不同 → 输入矩阵本身不同，误差不可直接比较。') +
    table('检查项', data.checks, '') +
    table('检验指标', data.selfcheck, '中位数与均值差异是最终要解释的量。') +
    `<div class="card"><h2>输入文件指纹</h2><p class="sub">大小或 mtime 不同，说明喂进去的数据不是同一份。</p>
      <div class="table-wrap"><table><thead><tr><th>输入</th><th>A</th><th>B</th></tr></thead><tbody>
      ${['exposures', 'returns', 'barra_root'].map((k) => {
        const fmt = (x) => {
          if (!x) return '—';
          const bits = [x.path];
          if (x.size_bytes != null) bits.push(Number(x.size_bytes).toLocaleString() + ' B');
          if (x.modified_utc) bits.push(x.modified_utc);
          return bits.join(' · ');
        };
        const av = fmt(data.inputs.left[k]);
        const bv = fmt(data.inputs.right[k]);
        return `<tr><td>${k}</td><td class="mono ${av === bv ? 'same' : 'changed'}">${esc(av)}</td>
                <td class="mono ${av === bv ? 'same' : 'changed'}">${esc(bv)}</td></tr>`;
      }).join('')}
      </tbody></table></div></div>` +
    `<div class="card"><h2>误差序列对照</h2>
      ${data.overlap ? `<p class="sub">重合日期 ${data.overlap.dates.length} 天：
        A 在这段上中位数 ${pct(data.overlap.left_median_on_common)}，
        B ${pct(data.overlap.right_median_on_common)}。
        —— 只在重合区间比较，才能排除"窗口不同"这个干扰项。</p>` : '<p class="sub">两个 Run 没有足够重合的检验日期。</p>'}
      <div id="compare-chart" class="chart"></div></div>`;

  if (data.overlap) {
    draw('#compare-chart', [
      { x: data.overlap.dates, y: data.overlap.left, mode: 'lines', name: `A · ${left}`,
        line: { color: '#4da3ff', width: 1.6 } },
      { x: data.overlap.dates, y: data.overlap.right, mode: 'lines', name: `B · ${right}`,
        line: { color: '#f5b544', width: 1.6 } },
    ], { yaxis: Object.assign({}, AXIS, { tickformat: '.0%', title: '相对误差' }) });
  }
});

/* --------------------------------- form -------------------------------- */

$('#run-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  const button = $('#run-submit');
  button.disabled = true;
  button.textContent = '已提交，运行中…';
  try {
    const created = await api('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await loadRuns(created.run_id);
    startPolling(created.run_id);
  } catch (err) {
    alert('启动失败：' + err.message);
  } finally {
    button.disabled = false;
    button.textContent = '开始运行';
  }
});

function startPolling(runId) {
  if (state.poll) clearInterval(state.poll);
  state.poll = setInterval(async () => {
    const list = await api('/api/runs');
    state.runs = list.runs;
    const run = list.runs.find((r) => r.run_id === runId);
    if (!run) return;
    const row = $(`#runs-table tbody tr[data-run="${runId}"]`);
    if (row) row.querySelector('td:nth-child(2)').innerHTML = `<span class="pill ${esc(run.state)}">${esc(run.state)}</span>`;
    if (run.state !== 'running') {
      clearInterval(state.poll);
      state.poll = null;
      await loadRuns(runId);
    }
  }, 4000);
}

/* --------------------------------- boot -------------------------------- */

$('#refresh').addEventListener('click', () => loadRuns());
$('#run-select').addEventListener('change', (e) => selectRun(e.target.value));
loadRuns().catch((err) => {
  $('#badges').innerHTML = `<div class="badge danger"><div class="t">加载失败</div><div class="d">${esc(err.message)}</div></div>`;
});
