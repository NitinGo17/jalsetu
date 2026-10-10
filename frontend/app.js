/* ==========================================================================
   JalSetu — front-end application logic (v2)
   User-first: plain language, six languages, farmer units, one big answer,
   and an assistant you can talk to. No framework, no build step.
   ========================================================================== */
(function () {
  'use strict';

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  const nf = (d) => new Intl.NumberFormat('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
  function num(v, d) { return (v === null || v === undefined || Number.isNaN(v)) ? '—' : nf(d == null ? 0 : d).format(v); }
  const mm = (v) => (v === null || v === undefined) ? '—' : num(v, 1) + ' mm';
  const litres = (v) => (v === null || v === undefined) ? '—' : num(v, 0) + ' L';
  function icon(id, cls) { return '<svg class="icon ' + (cls || '') + '" aria-hidden="true"><use href="#i-' + id + '"/></svg>'; }

  function toast(msg, kind) {
    const host = $('#toastHost'); if (!host) return;
    const n = document.createElement('div');
    n.className = 'toast' + (kind === 'error' ? ' toast--error' : '');
    n.textContent = msg; host.appendChild(n);
    setTimeout(() => { n.style.opacity = '0'; setTimeout(() => n.remove(), 300); }, 4600);
  }

  // --- i18n ---------------------------------------------------------------
  const LANGS = window.JALSETU_LANGS || [{ code: 'en-IN', native: 'English' }];
  const DICT = window.JALSETU_I18N || { 'en-IN': {} };

  function t(key, fallback) {
    const lang = App.settings.lang || 'en-IN';
    const d = DICT[lang] || {};
    return d[key] || (DICT['en-IN'] || {})[key] || fallback || key;
  }
  function applyI18n(root) {
    $$('[data-i18n]', root || document).forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$('[data-i18n-ph]', root || document).forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
    document.documentElement.lang = App.settings.lang || 'en-IN';
  }
  function populateLanguages() {
    const sel = $('#langSelect');
    sel.innerHTML = LANGS.map((l) =>
      '<option value="' + esc(l.code) + '">' + esc(l.native) + '</option>').join('');
    sel.value = App.settings.lang || 'en-IN';
  }

  // --- Farmer area units --------------------------------------------------
  // Bigha varies by state; the value used is a common North-India approximation.
  const AREA_UNITS = [
    { id: 'hectare', factor: 1, key: 'unit.hectare' },
    { id: 'acre', factor: 0.404686, key: 'unit.acre' },
    { id: 'bigha', factor: 0.2529, key: 'unit.bigha' },
    { id: 'guntha', factor: 0.010117, key: 'unit.guntha' },
  ];
  function toHectares(value, unitId) {
    const u = AREA_UNITS.find((x) => x.id === unitId) || AREA_UNITS[0];
    return value * u.factor;
  }

  // --- Settings & store ---------------------------------------------------
  const Settings = {
    defaults: {
      apiBase: (location.protocol === 'http:' || location.protocol === 'https:') ? '' : 'http://127.0.0.1:8000',
      demo: false, scenario: '', lang: 'en-IN', areaUnit: 'acre',
    },
    load() { try { return Object.assign({}, this.defaults, JSON.parse(localStorage.getItem('jalsetu.settings') || '{}')); } catch (e) { return Object.assign({}, this.defaults); } },
    save(s) { localStorage.setItem('jalsetu.settings', JSON.stringify(s)); },
  };

  const App = {
    settings: Settings.load(),
    fields: [], lastResult: null, crops: [], meta: null, scenarios: [],
    cropFilter: 'all', sarvam: { configured: false }, chat: [], recording: null,
  };

  function apiBase() { return (App.settings.apiBase || '').replace(/\/$/, ''); }

  class ApiError extends Error { constructor(m, s, d) { super(m); this.status = s; this.data = d; } }

  async function apiFetch(path, options) {
    options = options || {};
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000);
    const isForm = options.body instanceof FormData;
    const headers = Object.assign({}, options.headers || {});
    if (!isForm) headers['Content-Type'] = 'application/json';
    try {
      const res = await fetch(apiBase() + path, Object.assign({}, options, { signal: ctrl.signal, headers }));
      const text = await res.text();
      let data = null; try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
      if (!res.ok) {
        let msg = 'Request failed (HTTP ' + res.status + ').';
        const d = data && data.detail;
        if (typeof d === 'string') msg = d;
        else if (d && typeof d === 'object') msg = d.message || JSON.stringify(d);
        else if (Array.isArray(d)) msg = d.map((x) => x.msg || '').join('; ');
        throw new ApiError(msg, res.status, data);
      }
      return data;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (err && err.name === 'AbortError') throw new ApiError('The request timed out.', 0);
      throw new ApiError('Could not reach JalSetu. Is the backend running?', 0);
    } finally { clearTimeout(timer); }
  }

  const Store = {
    loadFields() { try { return JSON.parse(localStorage.getItem('jalsetu.fields') || '[]'); } catch (e) { return []; } },
    saveFields(f) { localStorage.setItem('jalsetu.fields', JSON.stringify(f)); },
    loadResult() { try { return JSON.parse(localStorage.getItem('jalsetu.lastResult') || 'null'); } catch (e) { return null; } },
    saveResult(r) { if (r) localStorage.setItem('jalsetu.lastResult', JSON.stringify(r)); else localStorage.removeItem('jalsetu.lastResult'); },
  };
  function uid() { return 'f' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }

  // --- Sarvam helpers (all proxied through the backend) --------------------
  function sarvamReady() { return !!App.sarvam.configured; }

  async function sarvamTranslate(text, target) {
    const d = await apiFetch('/api/translate', { method: 'POST', body: JSON.stringify({ text, target_language_code: target }) });
    return d.translated_text;
  }
  async function sarvamTTS(text, lang) {
    const d = await apiFetch('/api/tts', { method: 'POST', body: JSON.stringify({ text: text.slice(0, 2400), language_code: lang }) });
    return d.audio_base64;
  }
  async function sarvamSTT(blob) {
    const fd = new FormData();
    fd.append('file', blob, 'clip.webm');
    fd.append('language_code', App.settings.lang || 'en-IN');
    return apiFetch('/api/stt', { method: 'POST', body: fd });
  }
  async function sarvamChat(messages, context) {
    const d = await apiFetch('/api/chat', { method: 'POST', body: JSON.stringify({ messages, language_code: App.settings.lang || 'en-IN', context: context || null }) });
    return d.reply;
  }
  async function sarvamVision(file, question) {
    const fd = new FormData();
    fd.append('file', file, file.name || 'photo.jpg');
    fd.append('question', question || '');
    fd.append('language_code', App.settings.lang || 'en-IN');
    return apiFetch('/api/vision', { method: 'POST', body: fd });
  }

  function speak(text) {
    if (!sarvamReady()) { toast(t('notready.voice')); return; }
    const btn = $('#speakBtn');
    if (btn) btn.disabled = true;
    sarvamTTS(text, App.settings.lang || 'en-IN').then((b64) => {
      const player = $('#player');
      player.src = 'data:audio/mpeg;base64,' + b64;
      player.play().catch(() => {});
    }).catch((e) => toast(e.message, 'error'))
      .finally(() => { if (btn) btn.disabled = false; });
  }

  // --- Routing ------------------------------------------------------------
  const ROUTES = ['dashboard', 'analysis', 'results', 'fields', 'ask', 'crops', 'weather', 'settings'];
  const TITLES = {
    dashboard: ['nav.dashboard', 'app.tagline'],
    analysis: ['nav.analysis', 'form.subtitle'],
    results: ['nav.results', 'result.title'],
    fields: ['nav.fields', 'app.tagline'],
    ask: ['nav.ask', 'chat.subtitle'],
    crops: ['nav.crops', 'app.tagline'],
    weather: ['nav.weather', 'app.tagline'],
    settings: ['nav.settings', 'app.tagline'],
  };
  function currentRoute() { const h = (location.hash || '').replace(/^#\/?/, ''); return ROUTES.includes(h) ? h : 'dashboard'; }
  function navigate(r) { if (location.hash === '#/' + r) applyRoute(); else location.hash = '#/' + r; }

  function applyRoute() {
    const route = currentRoute();
    $$('.view').forEach((v) => {
      const on = v.id === 'view-' + route;
      v.hidden = !on;
      if (on) { v.classList.remove('enter'); void v.offsetWidth; v.classList.add('enter'); }
    });
    $$('[data-route]').forEach((b) => b.classList.toggle('is-active', b.dataset.route === route));
    $('#pageTitle').textContent = t(TITLES[route][0]);
    $('#pageSubtitle').textContent = t(TITLES[route][1]);
    if (route === 'dashboard') renderDashboard();
    if (route === 'results') renderResults();
    if (route === 'fields') renderFields();
    if (route === 'ask') renderAsk();
    if (route === 'crops') renderCrops();
    if (route === 'weather') renderWeather();
    if (route === 'settings') renderSettings();
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  // --- Shared fragments ---------------------------------------------------
  function statusKey(code) { return code === 'irrigate' ? 'result.irrigate' : code === 'wait' ? 'result.wait' : 'result.inspect'; }
  function statusClass(code) { return code === 'irrigate' ? 'irrigate' : code === 'wait' ? 'wait' : 'inspect'; }
  function badgeClass(code) { return code === 'irrigate' ? 'badge--ok' : code === 'wait' ? 'badge--wait' : 'badge--inspect'; }
  function statusIcon(code) { return code === 'irrigate' ? 'drop' : code === 'wait' ? 'cloud' : 'search'; }
  function waterBadge(st) {
    if (st === 'sufficient') return '<span class="badge badge--ok">' + icon('check') + ' ' + esc(t('result.yes')) + '</span>';
    if (st === 'insufficient') return '<span class="badge badge--inspect">' + icon('alert') + ' ' + esc(t('result.no')) + '</span>';
    return '<span class="badge badge--muted">—</span>';
  }
  function sourceBadge(w) {
    if (!w) return '';
    return w.is_demo ? '<span class="badge badge--demo">' + icon('info') + ' ' + esc(t('top.practice')) + '</span>'
      : '<span class="badge badge--live">' + icon('check') + ' ' + esc(t('top.ready')) + '</span>';
  }
  function practiceBanner(w) {
    if (!w || !w.is_demo) return '';
    return '<div class="banner banner--demo">' + icon('info') + '<div><strong>' + esc(t('top.practice')) +
      '</strong> ' + esc(t('practice.note')) + '</div></div>';
  }
  function loadingState(msg) { return '<div class="state"><div class="spinner"></div><p class="muted">' + esc(msg || t('common.loading')) + '</p></div>'; }
  function emptyState(title, body, action) {
    return '<div class="state"><div class="state__icon">' + icon('sprout') + '</div><h3>' + esc(title) +
      '</h3><p class="muted">' + esc(body) + '</p>' + (action || '') + '</div>';
  }

  // --- Charts -------------------------------------------------------------
  function forecastChart(forecast) {
    if (!forecast || !forecast.length) return '<p class="muted small">—</p>';
    const rows = forecast.slice(0, 7); const vals = [];
    rows.forEach((d) => { if (typeof d.rainfall_mm === 'number') vals.push(d.rainfall_mm); if (typeof d.et0_mm === 'number') vals.push(d.et0_mm); });
    const max = Math.max(1, ...vals);
    let cols = '';
    rows.forEach((d) => {
      const rain = typeof d.rainfall_mm === 'number' ? d.rainfall_mm : 0;
      const et0 = typeof d.et0_mm === 'number' ? d.et0_mm : 0;
      const day = d.date ? new Date(d.date + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short' }) : '';
      cols += '<div class="bar-chart__col" title="' + esc(d.date || '') + '"><div class="bar-chart__bars">' +
        '<div class="bar-chart__bar bar-chart__bar--rain" style="height:' + Math.max(2, Math.round(rain / max * 100)) + '%"></div>' +
        '<div class="bar-chart__bar bar-chart__bar--et0" style="height:' + Math.max(2, Math.round(et0 / max * 100)) + '%"></div>' +
        '</div><span class="bar-chart__label">' + esc(day) + '</span>' +
        '<span class="bar-chart__label mono">' + (typeof d.tmax === 'number' ? num(d.tmax, 0) + '°' : '—') + '</span></div>';
    });
    return '<div class="bar-chart">' + cols + '</div>' +
      '<div class="legend" style="margin-top:var(--sp-3)"><span><i style="background:var(--info)"></i> ' + mm(0).replace('0.0', '') + 'mm rain</span>' +
      '<span><i style="background:var(--emerald-500)"></i> ET₀</span></div>';
  }
  function splitBar(rain, net) {
    const total = (rain || 0) + (net || 0);
    if (total <= 0) return '<p class="muted small">—</p>';
    const rPct = Math.max(0, Math.min(100, (rain / total) * 100)); const nPct = 100 - rPct;
    return '<div class="split-bar">' +
      (rPct > 0 ? '<div class="split-bar__seg split-bar__seg--rain" style="width:' + rPct + '%"></div>' : '') +
      (nPct > 0 ? '<div class="split-bar__seg split-bar__seg--net" style="width:' + nPct + '%"></div>' : '') +
      '</div>';
  }

  // --- Dashboard ----------------------------------------------------------
  function renderDashboard() {
    const host = $('#dashboardBody'); const r = App.lastResult;
    if (!r) {
      host.innerHTML = '<div class="card"><div class="card__body">' +
        emptyState(t('nav.dashboard'), t('hero.sub'),
          '<button class="btn btn--primary btn--lg" data-go="analysis">' + icon('plus') + ' ' + esc(t('form.submit')) + '</button>') +
        '</div></div>' +
        '<div class="card" style="margin-top:var(--sp-4)"><div class="card__head"><h3>' + esc(t('top.example')) +
        '</h3></div><div class="card__body grid grid--3" id="dashScenarios"></div></div>';
      renderScenarioCards($('#dashScenarios'));
      return;
    }
    const rec = r.recommendation; const m = rec.metrics; const w = r.weather;
    host.innerHTML = bigAnswer(rec, m, true) +
      '<div class="grid grid--2" style="margin-top:var(--sp-4);align-items:start">' +
        '<div class="card"><div class="card__head"><h3>' + esc(t('nav.weather')) + '</h3>' + sourceBadge(w) + '</div>' +
          '<div class="card__body">' + (w ? forecastChart(w.forecast) : '—') + '</div></div>' +
        '<div class="card"><div class="card__head"><h3>' + esc(t('result.water')) + '</h3></div>' +
          '<div class="card__body">' + splitBar(m.effective_rainfall_mm, m.net_irrigation_mm) + '</div></div>' +
      '</div>' +
      '<div class="row row--between wrap" style="margin-top:var(--sp-4)">' +
        '<span class="small muted">' + esc(r.submittedAt ? new Date(r.submittedAt).toLocaleString('en-IN') : '') + '</span>' +
        '<span class="row"><button class="btn btn--ghost btn--sm" data-go="results">' + icon('eye') + ' ' + esc(t('nav.results')) + '</button>' +
        '<button class="btn btn--primary btn--sm" data-go="analysis">' + icon('plus') + ' ' + esc(t('form.submit')) + '</button></span></div>' +
      practiceBanner(w);
  }

  // The single, plain, big answer — the whole point of the redesign.
  function bigAnswer(rec, m, compact) {
    const code = rec.recommendation_code;
    const areaHa = (rec.inputs_echo && rec.inputs_echo.area_ha);
    const netL = m.net_volume_l;
    return '<div class="answer answer--' + statusClass(code) + '">' +
      '<div class="answer__icon">' + icon(statusIcon(code)) + '</div>' +
      '<div class="answer__main">' +
        '<div class="answer__label">' + esc(t('result.title')) + '</div>' +
        '<div class="answer__status">' + esc(t(statusKey(code))) + '</div>' +
        (netL ? '<div class="answer__water">' + esc(t('result.water')) + ': <strong>' + litres(netL) + '</strong>' +
          (areaHa ? ' <span class="answer__area">(' + mm(m.net_irrigation_mm) + ' ' + '·' + ' ' + num(areaHa, 2) + ' ha)</span>' : '') + '</div>'
          : '') +
        '<div class="answer__facts">' +
          '<span class="fact"><b>' + esc(t('result.demand')) + '</b> ' + mm(m.crop_water_demand_mm) + '</span>' +
          '<span class="fact"><b>' + esc(t('result.rain')) + '</b> ' + mm(m.effective_rainfall_mm) + '</span>' +
          '<span class="fact"><b>' + esc(t('result.have')) + '</b> ' + (m.available_water_l == null ? '—' : litres(m.available_water_l)) + '</span>' +
          '<span class="fact"><b>' + esc(t('result.status')) + '</b> ' + waterBadge(m.water_status) + '</span>' +
        '</div>' +
        '<div class="answer__actions">' +
          '<button class="btn btn--dark btn--sm" id="speakBtn"' + (sarvamReady() ? '' : ' title="' + esc(t('notready.voice')) + '"') + '>' + icon('volume') + ' ' + esc(t('result.speak')) + '</button>' +
          (compact ? '' : '<button class="btn btn--ghost btn--sm" data-go="ask">' + icon('chat') + ' ' + esc(t('chat.title')) + '</button>') +
        '</div>' +
      '</div></div>';
  }

  function speakSentence(rec, m) {
    const code = rec.recommendation_code;
    const parts = [t(statusKey(code))];
    if (m.net_volume_l) parts.push(t('result.water') + ' ' + num(m.net_volume_l, 0) + ' ' + 'litre');
    return parts.join('. ') + '.';
  }

  // Plain-language reasons, fully localised — no English leaks for non-English users.
  function localizedWhy(rec, m) {
    const code = rec.recommendation_code;
    const out = [];
    if (code === 'irrigate') out.push(t('why.irrigate'));
    else if (code === 'wait') out.push(t('why.wait'));
    else if (m.water_status === 'insufficient') out.push(t('why.inspect'));
    else out.push(t('why.more_data'));
    if (m.water_status === 'sufficient') out.push(t('why.water_enough'));
    if (m.water_status === 'insufficient') out.push(t('why.water_short'));
    if ((m.forecast_rainfall_mm || 0) > 0) out.push(t('why.rain_counted'));
    return out;
  }

  function scenarioName(id, fallback) { return t('sc.' + id, fallback || id); }

  function populateScenarioSelect() {
    const sel = $('#scenarioSelect');
    if (!sel) return;
    sel.innerHTML = '<option value="">—</option>' + App.scenarios.map((s) =>
      '<option value="' + esc(s.id) + '">' + esc(scenarioName(s.id, s.name)) + '</option>').join('');
    sel.value = App.settings.scenario || '';
  }

  // --- Results ------------------------------------------------------------
  function renderResults() {
    const host = $('#resultsBody'); const r = App.lastResult;
    if (!r) { host.innerHTML = emptyState(t('nav.results'), t('hero.sub'), '<button class="btn btn--primary" data-go="analysis">' + icon('plus') + ' ' + esc(t('form.submit')) + '</button>'); return; }
    const rec = r.recommendation; const m = rec.metrics; const b = rec.breakdown; const w = r.weather; const echo = rec.inputs_echo || {};

    const rows = [
      ['ET₀', 'from forecast', mm(b.et0_mm)],
      ['Kc', esc(echo.growth_stage || ''), b.kc == null ? '—' : num(b.kc, 2)],
      [t('result.demand'), 'ET₀ × Kc', mm(b.crop_water_demand_mm)],
      [t('result.rain'), 'min(P, ETc)', mm(b.effective_rainfall_mm)],
      ['Net requirement', 'max(0, ETc − Pe)', mm(b.net_irrigation_mm)],
      ['Efficiency', esc(echo.irrigation_method || ''), b.irrigation_efficiency == null ? '—' : num(b.irrigation_efficiency * 100, 0) + '%'],
      ['Gross applied', 'NIR ÷ efficiency', mm(b.gross_irrigation_mm)],
      ['Net volume', num(b.area_ha, 2) + ' ha × 10,000', litres(b.net_volume_l)],
      ['Gross volume', 'after losses', litres(b.gross_volume_l)],
    ].map((x) => '<tr><td>' + x[0] + '</td><td class="muted small">' + x[1] + '</td><td>' + x[2] + '</td></tr>').join('');

    host.innerHTML =
      '<div class="row row--between wrap" style="margin-bottom:var(--sp-3)">' +
        '<span class="row wrap">' + sourceBadge(w) +
        '<span class="badge badge--outline">' + icon('calendar') + ' ' + esc((w && w.planning_day && w.planning_day.date) || '—') + '</span></span>' +
        '<button class="btn btn--ghost btn--sm" data-go="analysis">' + icon('plus') + ' ' + esc(t('result.new')) + '</button></div>' +

      bigAnswer(rec, m, false) +

      (rec.warnings && rec.warnings.length ? '<div class="stack" style="margin-top:var(--sp-3)">' +
        rec.warnings.map((x) => '<div class="banner banner--warn">' + icon('alert') + '<div>' + esc(x) + '</div></div>').join('') + '</div>' : '') +

      '<div class="card" style="margin-top:var(--sp-4)"><div class="card__head"><h3>' + esc(t('result.why')) +
        '</h3><button class="btn btn--ghost btn--sm" id="translateBtn" ' + (sarvamReady() ? '' : 'hidden') + '>' + esc(t('action.translate')) + '</button></div>' +
        '<div class="card__body"><ul class="note-list" id="whyList">' +
        localizedWhy(rec, m).map((x) => '<li>' + icon('check') + '<span>' + esc(x) + '</span></li>').join('') +
        '</ul></div></div>' +

      '<details class="disclose" style="margin-top:var(--sp-4)"><summary>' + icon('gauge') + ' ' + esc(t('result.how')) + '</summary>' +
        '<div class="card" style="margin-top:var(--sp-3)"><div class="card__body table-scroll">' +
        '<table class="breakdown"><thead><tr><th>Step</th><th>Basis</th><th>Value</th></tr></thead><tbody>' + rows + '</tbody></table>' +
        '<p class="tiny muted" style="margin-top:var(--sp-3)">1 mm over 1 hectare = 10,000 litres. ' + esc(b.conversion || '') + '</p>' +
        '<div class="grid grid--2" style="margin-top:var(--sp-4)">' +
          '<div>' + splitBar(m.effective_rainfall_mm, m.net_irrigation_mm) + '</div>' +
          '<div>' + (w ? forecastChart(w.forecast) : '') + '</div>' +
        '</div>' +
        '<h4 class="small" style="margin-top:var(--sp-4)">Detailed reasons (English)</h4>' +
        '<ul class="note-list note-list--assume">' +
        rec.reasons.map((x) => '<li>' + icon('check') + '<span>' + esc(x) + '</span></li>').join('') +
        '</ul>' +
        '<h4 class="small" style="margin-top:var(--sp-4)">Assumptions</h4>' +
        '<ul class="note-list note-list--assume">' +
        rec.assumptions.map((x) => '<li>' + icon('info') + '<span>' + esc(x) + '</span></li>').join('') +
        '</ul></div></div></details>' +

      practiceBanner(w);

    const sb = $('#speakBtn'); if (sb) sb.addEventListener('click', () => speak(speakSentence(rec, m)));
    const tb = $('#translateBtn');
    if (tb && sarvamReady()) tb.addEventListener('click', async () => {
      tb.disabled = true;
      try {
        const joined = rec.reasons.join('\n');
        const out = await sarvamTranslate(joined, App.settings.lang || 'hi-IN');
        $('#whyList').innerHTML = out.split('\n').filter(Boolean).map((x) => '<li>' + icon('check') + '<span>' + esc(x) + '</span></li>').join('');
      } catch (e) { toast(e.message, 'error'); } finally { tb.disabled = false; }
    });
  }

  // --- Analysis form ------------------------------------------------------
  function populateSelects() {
    const cropOpts = App.crops.map((c) => '<option value="' + esc(c.id) + '">' + esc(c.name) + (c.local_name ? ' · ' + esc(c.local_name) : '') + '</option>').join('');
    const stageOpts = (App.meta ? App.meta.growth_stages : []).map((s) => '<option value="' + esc(s.id) + '">' + esc(s.label) + '</option>').join('');
    const soilOpts = (App.meta ? App.meta.soil_types : []).map((s) => '<option value="' + esc(s.id) + '">' + esc(s.label) + '</option>').join('');
    const methodOpts = (App.meta ? App.meta.irrigation_methods : []).map((x) => '<option value="' + esc(x.id) + '">' + esc(x.label) + ' (' + num(x.efficiency * 100, 0) + '%)</option>').join('');
    ['#f-crop', '#df-crop'].forEach((s) => { const e = $(s); if (e) e.innerHTML = cropOpts; });
    ['#f-stage', '#df-stage'].forEach((s) => { const e = $(s); if (e) e.innerHTML = stageOpts; });
    ['#f-soil', '#df-soil'].forEach((s) => { const e = $(s); if (e) e.innerHTML = soilOpts; });
    ['#f-method', '#df-method'].forEach((s) => { const e = $(s); if (e) e.innerHTML = methodOpts; });
    const unitOpts = AREA_UNITS.map((u) => '<option value="' + u.id + '">' + esc(t(u.key)) + '</option>').join('');
    const us = $('#f-area-unit'); if (us) { us.innerHTML = unitOpts; us.value = App.settings.areaUnit || 'acre'; }
  }

  function clearErrors() { $$('.field.has-error').forEach((f) => f.classList.remove('has-error')); $$('[data-error-for]').forEach((e) => { e.textContent = ''; }); }
  function setError(id, msg) { const i = document.getElementById(id); if (i && i.closest('.field')) i.closest('.field').classList.add('has-error'); const e = $('[data-error-for="' + id + '"]'); if (e) e.textContent = msg; }

  function readForm() {
    const areaVal = $('#f-area').value === '' ? null : Number($('#f-area').value);
    const unit = $('#f-area-unit').value;
    return {
      field_name: ($('#f-name').value || '').trim() || 'Field',
      crop_id: $('#f-crop').value, growth_stage: $('#f-stage').value, soil_type: $('#f-soil').value,
      area_ha: areaVal === null ? null : toHectares(areaVal, unit),
      irrigation_method: $('#f-method').value,
      available_water_l: $('#f-water').value === '' ? null : Number($('#f-water').value),
    };
  }

  function validate(field, location, isPractice) {
    let ok = true;
    if (!field.crop_id) { setError('f-crop', 'Required'); ok = false; }
    if (!field.growth_stage) { setError('f-stage', 'Required'); ok = false; }
    if (!field.soil_type) { setError('f-soil', 'Required'); ok = false; }
    if (!field.irrigation_method) { setError('f-method', 'Required'); ok = false; }
    if (field.area_ha === null || Number.isNaN(field.area_ha)) { setError('f-area', 'Enter the size'); ok = false; }
    else if (field.area_ha <= 0) { setError('f-area', 'Must be more than 0'); ok = false; }
    else if (field.area_ha > 10000) { setError('f-area', 'Too large'); ok = false; }
    if (field.available_water_l !== null && (Number.isNaN(field.available_water_l) || field.available_water_l < 0)) { setError('f-water', 'Cannot be negative'); ok = false; }
    if (!location && !isPractice) { setError('f-location', 'Enter a place, or turn on practice weather'); ok = false; }
    return ok;
  }

  async function submitAnalysis(e) {
    if (e) e.preventDefault();
    clearErrors();
    const field = readForm(); const location = ($('#f-location').value || '').trim();
    const isPractice = App.settings.demo || !!App.settings.scenario;
    if (!validate(field, location, isPractice)) { toast(t('common.error'), 'error'); return; }
    App.settings.areaUnit = $('#f-area-unit').value; Settings.save(App.settings);

    const btn = $('#analyseBtn'); const orig = btn.innerHTML; btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:16px;height:16px;border-width:2px;margin:0"></span>';

    const payload = { field: field, demo: isPractice };
    if (location) payload.location = location;
    if (App.settings.scenario) {
      payload.scenario = App.settings.scenario;
      const sc = App.scenarios.find((s) => s.id === App.settings.scenario);
      if (sc && sc.field) { payload.latitude = sc.field.latitude; payload.longitude = sc.field.longitude; }
    }
    try {
      const data = await apiFetch('/api/recommendation', { method: 'POST', body: JSON.stringify(payload) });
      App.lastResult = { recommendation: data.recommendation, weather: data.weather, submittedAt: new Date().toISOString(), request: { field, location, demo: isPractice, scenario: App.settings.scenario || null } };
      Store.saveResult(App.lastResult);
      toast(t(statusKey(data.recommendation.recommendation_code)));
      navigate('results');
    } catch (err) { toast(err.message, 'error'); }
    finally { btn.disabled = false; btn.innerHTML = orig; }
  }

  function fillFromScenario(id) {
    const sc = App.scenarios.find((s) => s.id === id); if (!sc || !sc.field) return;
    const f = sc.field;
    $('#f-name').value = f.field_name || '';
    $('#f-location').value = f.location || '';
    $('#f-crop').value = f.crop_id || ''; $('#f-stage').value = f.growth_stage || '';
    $('#f-soil').value = f.soil_type || ''; $('#f-method').value = f.irrigation_method || '';
    $('#f-area-unit').value = 'hectare';
    $('#f-area').value = f.area_ha != null ? f.area_ha : '';
    $('#f-water').value = f.available_water_l != null ? f.available_water_l : '';
    clearErrors();
  }

  function renderScenarioCards(host) {
    if (!host) return;
    host.innerHTML = App.scenarios.map((s) =>
      '<button type="button" class="scenario-card' + (App.settings.scenario === s.id ? ' is-active' : '') + '" data-scenario="' + esc(s.id) + '">' +
      '<h4>' + esc(scenarioName(s.id, s.name)) + '</h4><p class="small muted" style="margin:0 0 .4rem">' + esc(t('sc.' + s.id + '.desc', s.description)) + '</p>' +
      '<span class="badge badge--outline">ET₀ ' + num(s.weather.et0_mm, 1) + ' · ' + num(s.weather.rainfall_mm, 1) + ' mm</span></button>').join('') ||
      '<p class="muted small">—</p>';
    $$('[data-scenario]', host).forEach((b) => b.addEventListener('click', () => runScenario(b.dataset.scenario)));
  }
  async function runScenario(id) {
    App.settings.scenario = id; App.settings.demo = true; Settings.save(App.settings);
    $('#demoToggle').checked = true; $('#scenarioSelect').value = id;
    fillFromScenario(id);
    if (currentRoute() !== 'analysis') navigate('analysis');
    await submitAnalysis();
  }

  // --- My fields ----------------------------------------------------------
  function renderFields() {
    const host = $('#fieldsBody');
    if (!App.fields.length) { host.innerHTML = emptyState(t('nav.fields'), t('hero.sub'), '<button class="btn btn--primary" data-go="analysis">' + icon('plus') + ' ' + esc(t('form.submit')) + '</button>'); return; }
    const rows = App.fields.map((f) => {
      const st = f.lastStatus;
      const badge = st ? '<span class="badge ' + badgeClass(st.code) + '">' + esc(t(statusKey(st.code))) + '</span>' : '<span class="badge badge--muted">—</span>';
      return '<tr><td><strong>' + esc(f.field_name) + '</strong><div class="tiny muted">' + esc(f.location || '') + '</div></td>' +
        '<td>' + esc(f.crop_id) + '</td><td>' + num(f.area_ha, 2) + ' ha</td><td>' + badge + '</td>' +
        '<td><div class="data-table__actions">' +
        '<button class="btn btn--ghost btn--sm" data-analyse="' + esc(f.id) + '">' + esc(t('nav.analysis')) + '</button>' +
        '<button class="btn btn--ghost btn--sm" data-edit="' + esc(f.id) + '">' + icon('pencil') + '</button>' +
        '<button class="btn btn--danger btn--sm" data-delete="' + esc(f.id) + '">' + icon('trash') + '</button>' +
        '</div></td></tr>';
    }).join('');
    host.innerHTML = '<div class="table-scroll"><table class="data-table"><thead><tr><th>' + esc(t('nav.fields')) + '</th><th>' + esc(t('form.crop')) + '</th><th>' + esc(t('form.area')) + '</th><th>' + esc(t('result.title')) + '</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div>';
    $$('[data-edit]', host).forEach((b) => b.addEventListener('click', () => openFieldDialog(b.dataset.edit)));
    $$('[data-delete]', host).forEach((b) => b.addEventListener('click', () => deleteField(b.dataset.delete)));
    $$('[data-analyse]', host).forEach((b) => b.addEventListener('click', () => analyseField(b.dataset.analyse)));
  }
  function openFieldDialog(id) {
    const f = id ? App.fields.find((x) => x.id === id) : null;
    $('#fieldDialogTitle').textContent = f ? t('nav.fields') : 'Add';
    $('#df-id').value = f ? f.id : ''; $('#df-name').value = f ? f.field_name : '';
    $('#df-crop').value = f ? f.crop_id : ($('#f-crop').value || 'wheat');
    $('#df-stage').value = f ? f.growth_stage : ($('#f-stage').value || 'vegetative');
    $('#df-soil').value = f ? f.soil_type : ($('#f-soil').value || 'loamy');
    $('#df-method').value = f ? f.irrigation_method : ($('#f-method').value || 'drip');
    $('#df-area').value = f ? f.area_ha : ''; $('#df-water').value = f && f.available_water_l != null ? f.available_water_l : '';
    $('#df-location').value = f ? (f.location || '') : ($('#f-location').value || '');
    $('#df-error').textContent = '';
    const d = $('#fieldDialog'); if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
  }
  function saveField(e) {
    if (e) e.preventDefault();
    const name = $('#df-name').value.trim(); const area = $('#df-area').value === '' ? null : Number($('#df-area').value);
    if (!name) { $('#df-error').textContent = 'Enter a name'; return; }
    if (area === null || Number.isNaN(area) || area <= 0) { $('#df-error').textContent = 'Enter a size above 0'; return; }
    const data = { field_name: name, crop_id: $('#df-crop').value, growth_stage: $('#df-stage').value, soil_type: $('#df-soil').value, irrigation_method: $('#df-method').value, area_ha: area, available_water_l: $('#df-water').value === '' ? null : Number($('#df-water').value), location: $('#df-location').value.trim() };
    const id = $('#df-id').value;
    if (id) { const i = App.fields.findIndex((x) => x.id === id); App.fields[i] = Object.assign({}, App.fields[i], data); }
    else App.fields.push(Object.assign({ id: uid(), lastStatus: null }, data));
    Store.saveFields(App.fields); $('#fieldDialog').close(); renderFields(); toast('Saved');
  }
  function deleteField(id) {
    const f = App.fields.find((x) => x.id === id); if (!f) return;
    if (!confirm('Delete "' + f.field_name + '"?')) return;
    App.fields = App.fields.filter((x) => x.id !== id); Store.saveFields(App.fields); renderFields(); toast('Deleted');
  }
  async function analyseField(id) {
    const f = App.fields.find((x) => x.id === id); if (!f) return;
    const payload = { field: { field_name: f.field_name, crop_id: f.crop_id, growth_stage: f.growth_stage, soil_type: f.soil_type, area_ha: f.area_ha, irrigation_method: f.irrigation_method, available_water_l: f.available_water_l }, demo: true, scenario: App.settings.scenario || 'dry' };
    if (f.location) payload.location = f.location;
    try {
      const data = await apiFetch('/api/recommendation', { method: 'POST', body: JSON.stringify(payload) });
      f.lastStatus = { code: data.recommendation.recommendation_code }; Store.saveFields(App.fields);
      App.lastResult = { recommendation: data.recommendation, weather: data.weather, submittedAt: new Date().toISOString(), request: { field: payload.field, location: f.location, demo: true, scenario: payload.scenario } };
      Store.saveResult(App.lastResult); renderFields(); toast(t(statusKey(f.lastStatus.code)));
    } catch (e) { toast(e.message, 'error'); }
  }
  async function loadSamples() {
    const samples = [
      { field_name: 'Main Field', crop_id: 'wheat', growth_stage: 'flowering', soil_type: 'loamy', area_ha: 1.0, irrigation_method: 'drip', available_water_l: 100000, location: 'Prayagraj, Uttar Pradesh' },
      { field_name: 'North Plot', crop_id: 'rice', growth_stage: 'vegetative', soil_type: 'clay', area_ha: 0.2, irrigation_method: 'flood', available_water_l: 20000, location: 'Nashik, Maharashtra' },
      { field_name: 'East Plot', crop_id: 'maize', growth_stage: 'vegetative', soil_type: 'black', area_ha: 0.2, irrigation_method: 'sprinkler', available_water_l: 40000, location: 'Nashik, Maharashtra' },
    ];
    samples.forEach((s) => App.fields.push(Object.assign({ id: uid(), lastStatus: null }, s)));
    Store.saveFields(App.fields); renderFields();
    for (const s of App.fields.slice(-3)) await analyseField(s.id);
  }

  // --- Crops --------------------------------------------------------------
  function renderCrops() {
    const host = $('#cropsBody');
    if (!App.crops.length) { host.innerHTML = loadingState(); return; }
    const cats = ['all'].concat(Array.from(new Set(App.crops.map((c) => c.category))));
    $('#cropFilters').innerHTML = cats.map((c) => '<button type="button" class="chip' + (App.cropFilter === c ? ' is-active' : '') + '" data-cat="' + esc(c) + '">' + esc(c === 'all' ? 'All' : c) + '</button>').join('');
    $$('#cropFilters [data-cat]').forEach((b) => b.addEventListener('click', () => { App.cropFilter = b.dataset.cat; renderCrops(); }));
    const list = App.crops.filter((c) => App.cropFilter === 'all' || c.category === App.cropFilter);
    host.innerHTML = '<div class="table-scroll"><table class="data-table"><thead><tr><th>Crop</th><th>Kc initial</th><th>Kc veg.</th><th>Kc flowering</th><th>Kc maturity</th><th>Root</th><th>Source</th></tr></thead><tbody>' +
      list.map((c) => '<tr><td><strong>' + esc(c.name) + '</strong><div class="tiny muted">' + esc(c.local_name || '') + '</div></td>' +
        '<td class="mono">' + num(c.kc.initial, 2) + '</td><td class="mono">' + num(c.kc.vegetative, 2) + '</td><td class="mono">' + num(c.kc.flowering, 2) + '</td><td class="mono">' + num(c.kc.maturity, 2) + '</td>' +
        '<td>' + num(c.root_depth_m, 1) + ' m</td><td class="small muted">' + esc(c.source) + '</td></tr>').join('') +
      '</tbody></table></div><div class="banner banner--info" style="margin-top:var(--sp-4)">' + icon('info') +
      '<div class="small">FAO-56 (Allen et al., 1998) indicative reference values. The vegetative column is a JalSetu interpolation.</div></div>';
  }

  // --- Weather ------------------------------------------------------------
  let weatherState = null;
  function renderWeather() {
    const host = $('#weatherBody');
    if (!weatherState) { host.innerHTML = emptyState(t('nav.weather'), t('form.location.hint')); return; }
    if (weatherState.loading) { host.innerHTML = loadingState(); return; }
    if (weatherState.error) { host.innerHTML = '<div class="state">' + icon('alert') + '<p class="muted">' + esc(weatherState.error) + '</p></div>'; return; }
    const w = weatherState.data; const c = w.current || {}; const rs = w.rainfall_summary || {};
    host.innerHTML = '<div class="row wrap" style="margin-bottom:var(--sp-3)">' + sourceBadge(w) +
      '<span class="badge badge--outline">' + icon('pin') + ' ' + esc((w.location && w.location.name) || '—') + '</span>' +
      '<span class="badge badge--outline">' + esc(w.fetched_at || '') + '</span></div>' + practiceBanner(w) +
      '<div class="grid grid--stats" style="margin-top:var(--sp-3)">' +
      '<div class="stat"><div class="stat__icon stat__icon--demand">' + icon('thermo') + '</div><div><div class="stat__label">Temp</div><div class="stat__value">' + (c.temperature_2m != null ? num(c.temperature_2m, 1) + '°C' : '—') + '</div><div class="stat__sub">' + esc(c.weather_text || '') + '</div></div></div>' +
      '<div class="stat"><div class="stat__icon stat__icon--water">' + icon('drop') + '</div><div><div class="stat__label">Humidity</div><div class="stat__value">' + (c.relative_humidity_2m != null ? num(c.relative_humidity_2m, 0) + '%' : '—') + '</div></div></div>' +
      '<div class="stat"><div class="stat__icon stat__icon--rain">' + icon('wind') + '</div><div><div class="stat__label">Wind</div><div class="stat__value">' + (c.wind_speed_10m != null ? num(c.wind_speed_10m, 1) + ' km/h' : '—') + '</div></div></div>' +
      '<div class="stat"><div class="stat__icon stat__icon--status">' + icon('rain') + '</div><div><div class="stat__label">' + esc(t('result.rain')) + '</div><div class="stat__value">' + mm(rs.seven_day_total_mm) + '</div><div class="stat__sub">7 days</div></div></div>' +
      '</div><div class="card" style="margin-top:var(--sp-4)"><div class="card__body">' + forecastChart(w.forecast) + '</div></div>' +
      '<p class="tiny muted" style="margin-top:var(--sp-3)">Source: ' + esc(w.provider || '') + '</p>';
  }
  async function fetchWeather(loc, demo) {
    weatherState = { loading: true }; renderWeather();
    try { weatherState = { data: await apiFetch('/api/weather?' + (demo ? 'demo=true&scenario=dry' : 'location=' + encodeURIComponent(loc))) }; }
    catch (e) { weatherState = { error: e.message }; }
    renderWeather();
  }

  // --- Ask (chat + photo) -------------------------------------------------
  function renderAsk() {
    // Badges reflect whether Sarvam is on.
    const cb = $('#chatBadge'), pb = $('#photoBadge');
    const on = sarvamReady();
    [cb, pb].forEach((b) => { if (!b) return; b.className = 'badge ' + (on ? 'badge--live' : 'badge--muted'); b.textContent = on ? t('top.ready') : t('notready.title'); });
    if (!App.chat.length) App.chat.push({ role: 'assistant', content: t('chat.hello') });
    renderChatLog();
    const vs = $('#voiceStatus');
    if (vs) vs.textContent = on ? '' : t('notready.voice');
  }
  function renderChatLog() {
    const log = $('#chatLog'); if (!log) return;
    log.innerHTML = App.chat.map((m) => '<div class="msg msg--' + (m.role === 'user' ? 'user' : 'bot') + '"><div class="msg__bubble">' + esc(m.content) + '</div></div>').join('');
    log.scrollTop = log.scrollHeight;
  }
  async function sendChat(e) {
    if (e) e.preventDefault();
    const input = $('#chatInput'); const text = input.value.trim(); if (!text) return;
    if (!sarvamReady()) { toast(t('notready.assistant')); return; }
    App.chat.push({ role: 'user', content: text }); input.value = ''; renderChatLog();
    App.chat.push({ role: 'assistant', content: '…' }); renderChatLog();
    try {
      const ctx = App.lastResult ? { crop: App.lastResult.recommendation.crop && App.lastResult.recommendation.crop.name, growth_stage: App.lastResult.recommendation.inputs_echo.growth_stage, location: App.lastResult.request && App.lastResult.request.location, recommendation: t(statusKey(App.lastResult.recommendation.recommendation_code)), net_irrigation_mm: App.lastResult.recommendation.metrics.net_irrigation_mm, net_volume_l: App.lastResult.recommendation.metrics.net_volume_l, water_status: App.lastResult.recommendation.metrics.water_status } : null;
      const history = App.chat.filter((m) => m.content !== '…').map((m) => ({ role: m.role, content: m.content }));
      const reply = await sarvamChat(history, ctx);
      App.chat[App.chat.length - 1] = { role: 'assistant', content: reply };
    } catch (err) {
      App.chat[App.chat.length - 1] = { role: 'assistant', content: err.message };
    }
    renderChatLog();
  }
  function pickPhoto(e) {
    const f = e.target.files && e.target.files[0]; if (!f) return;
    const img = $('#photoPreview'); img.src = URL.createObjectURL(f); img.hidden = false;
    $('#photoDrop').classList.add('has-file');
  }
  async function sendPhoto() {
    const input = $('#photoInput'); const f = input.files && input.files[0];
    const out = $('#photoResult');
    if (!f) { toast(t('photo.choose')); return; }
    if (!sarvamReady()) { out.innerHTML = '<div class="banner banner--demo">' + icon('info') + '<div>' + esc(t('notready.photo')) + '</div></div>'; return; }
    out.innerHTML = loadingState();
    try { const d = await sarvamVision(f, $('#photoQuestion').value.trim()); out.innerHTML = '<div class="banner banner--info">' + icon('info') + '<div>' + esc(d.answer) + '</div></div>'; }
    catch (err) { out.innerHTML = '<div class="banner banner--warn">' + icon('alert') + '<div>' + esc(err.message) + '</div></div>'; }
  }
  async function toggleMic() {
    if (!sarvamReady()) { toast(t('notready.voice')); return; }
    if (App.recording) { App.recording.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { toast(t('notready.voice')); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks = []; const rec = new MediaRecorder(stream);
      App.recording = rec;
      $('#micBtn').classList.add('is-recording');
      rec.ondataavailable = (ev) => chunks.push(ev.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((x) => x.stop()); App.recording = null;
        $('#micBtn').classList.remove('is-recording');
        $('#voiceStatus').textContent = t('common.loading');
        try { const d = await sarvamSTT(new Blob(chunks, { type: 'audio/webm' })); $('#chatInput').value = d.transcript || ''; $('#voiceStatus').textContent = ''; }
        catch (err) { $('#voiceStatus').textContent = err.message; }
      };
      rec.start();
    } catch (e) { toast('Microphone not available', 'error'); }
  }

  // --- Settings -----------------------------------------------------------
  function renderSettings() {
    const host = $('#settingsBody');
    const on = sarvamReady();
    host.innerHTML = '<div class="grid grid--2" style="align-items:start">' +
      '<div class="card"><div class="card__head"><h3>' + esc(t('nav.settings')) + '</h3></div><div class="card__body stack">' +
        '<div class="field"><label>' + esc(t('top.language')) + '</label><select class="select" id="s-lang">' + LANGS.map((l) => '<option value="' + esc(l.code) + '"' + (App.settings.lang === l.code ? ' selected' : '') + '>' + esc(l.native) + '</option>').join('') + '</select></div>' +
        '<div class="field"><label>API base URL</label><input class="input" id="s-api" value="' + esc(App.settings.apiBase) + '" /></div>' +
        '<label class="switch"><input type="checkbox" id="s-demo"' + (App.settings.demo ? ' checked' : '') + '> ' + esc(t('top.practice')) + '</label>' +
        '<div class="row"><button class="btn btn--primary btn--sm" id="s-save">Save</button><button class="btn btn--ghost btn--sm" id="s-test">Test</button></div>' +
      '</div></div>' +
      '<div class="card"><div class="card__head"><h3>Sarvam AI</h3><span class="badge ' + (on ? 'badge--live' : 'badge--muted') + '">' + esc(on ? t('top.ready') : t('notready.title')) + '</span></div><div class="card__body stack">' +
        '<p class="small muted" style="margin:0">' + esc(App.sarvam.message || '') + '</p>' +
        ((App.sarvam.diagnostics && App.sarvam.diagnostics.hint && !App.sarvam.configured) ? '<p class="small" style="margin:0;color:var(--ink-600);overflow-wrap:anywhere">' + esc(App.sarvam.diagnostics.hint) + '</p>' : '') +
        '<div class="banner banner--info">' + icon('shield') + '<div class="small">The key lives in a server-side <code>.env</code> file as <code>SARVAM_API_KEY</code>. It is never sent to the browser and never stored here.</div></div>' +
        '<div class="row"><button class="btn btn--ghost btn--sm" id="s-clear-fields">Clear fields</button><button class="btn btn--ghost btn--sm" id="s-clear-result">Clear result</button></div>' +
      '</div></div></div>';
    $('#s-save').addEventListener('click', () => { App.settings.apiBase = $('#s-api').value.trim(); App.settings.demo = $('#s-demo').checked; Settings.save(App.settings); toast('Saved'); checkHealth(); });
    $('#s-lang').addEventListener('change', (e) => setLanguage(e.target.value));
    $('#s-test').addEventListener('click', checkHealth);
    $('#s-clear-fields').addEventListener('click', () => { App.fields = []; Store.saveFields(App.fields); renderSettings(); toast('Cleared'); });
    $('#s-clear-result').addEventListener('click', () => { App.lastResult = null; Store.saveResult(null); toast('Cleared'); });
  }

  async function checkHealth() {
    const b = $('#apiStatus'); b.textContent = t('top.checking'); b.className = 'badge badge--muted';
    try { const h = await apiFetch('/api/health'); b.textContent = 'v' + (h.version || '?'); b.className = 'badge badge--live'; }
    catch (e) { b.textContent = t('top.notconnected'); b.className = 'badge badge--inspect'; }
  }

  function setLanguage(code) {
    App.settings.lang = code; Settings.save(App.settings);
    populateLanguages(); applyI18n();
    App.chat = [{ role: 'assistant', content: t('chat.hello') }];
    const th = $('#toastHost'); if (th) th.innerHTML = '';
    populateScenarioSelect();
    populateSelects();
    renderScenarioCards($('#scenarioCards'));
    applyRoute();
  }

  // --- Boot ---------------------------------------------------------------
  async function boot() {
    App.fields = Store.loadFields(); App.lastResult = Store.loadResult();
    $('#demoToggle').checked = App.settings.demo;

    $$('[data-route]').forEach((b) => b.addEventListener('click', () => navigate(b.dataset.route)));
    document.addEventListener('click', (e) => { const g = e.target.closest('[data-go]'); if (g) navigate(g.dataset.go); });

    $('#langSelect').addEventListener('change', (e) => setLanguage(e.target.value));
    $('#demoToggle').addEventListener('change', (e) => { App.settings.demo = e.target.checked; if (!e.target.checked) { App.settings.scenario = ''; $('#scenarioSelect').value = ''; } Settings.save(App.settings); });
    $('#scenarioSelect').addEventListener('change', (e) => { App.settings.scenario = e.target.value; if (e.target.value) { App.settings.demo = true; $('#demoToggle').checked = true; fillFromScenario(e.target.value); if (currentRoute() !== 'analysis') navigate('analysis'); } Settings.save(App.settings); });

    $('#analysisForm').addEventListener('submit', submitAnalysis);
    $('#fillDemoBtn').addEventListener('click', () => { const id = App.settings.scenario || (App.scenarios[0] && App.scenarios[0].id); if (id) fillFromScenario(id); });
    $('#resetFormBtn').addEventListener('click', () => setTimeout(clearErrors, 0));

    $('#addFieldBtn').addEventListener('click', () => openFieldDialog(null));
    $('#loadSamplesBtn').addEventListener('click', loadSamples);
    $('#fieldForm').addEventListener('submit', saveField);
    $('#fieldDialogClose').addEventListener('click', () => $('#fieldDialog').close());
    $('#fieldCancelBtn').addEventListener('click', () => $('#fieldDialog').close());

    $('#weatherForm').addEventListener('submit', (e) => { e.preventDefault(); const d = $('#w-demo').checked; const l = $('#w-location').value.trim(); if (!d && !l) { toast(t('form.location')); return; } fetchWeather(l, d); });
    $('#w-demo').addEventListener('change', (e) => { if (e.target.checked) fetchWeather('', true); });

    $('#chatForm').addEventListener('submit', sendChat);
    $('#micBtn').addEventListener('click', toggleMic);
    $('#photoInput').addEventListener('change', pickPhoto);
    $('#photoSend').addEventListener('click', sendPhoto);

    window.addEventListener('hashchange', applyRoute);

    populateLanguages(); applyI18n();

    // Load reference data
    try { App.meta = await apiFetch('/api/meta'); } catch (e) {}
    try { App.crops = (await apiFetch('/api/crops')).crops || []; } catch (e) {}
    try { App.scenarios = (await apiFetch('/api/scenarios')).scenarios || []; } catch (e) {}
    try { App.sarvam = await apiFetch('/api/sarvam/status'); } catch (e) { App.sarvam = { configured: false, message: '' }; }

    populateSelects();
    populateScenarioSelect();
    renderScenarioCards($('#scenarioCards'));
    applyI18n();
    checkHealth();
    applyRoute();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
