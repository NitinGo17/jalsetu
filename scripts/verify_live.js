/*
 * Verify the LIVE weather path through the real UI:
 *  - Weather page: search a city with "Demo data" unchecked -> expect Live badge
 *  - Analysis form: submit with a location and demo off -> expect live weather
 *
 *   node scripts/verify_live.js
 */
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const puppeteer = require('/usr/lib/node_modules/puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const PORT = 8139;
const BASE = `http://127.0.0.1:${PORT}`;
const CHROME = '/usr/local/bin/chromium-headless-shell';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function ping(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.setTimeout(1500, () => { req.destroy(); resolve(false); });
  });
}

(async () => {
  const server = spawn('python', ['-m', 'uvicorn', 'backend.main:app', '--port', String(PORT)],
    { cwd: ROOT, stdio: 'ignore' });
  for (let i = 0; i < 60; i++) { if (await ping(BASE + '/api/health')) break; await sleep(500); }

  const errors = [];
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: CHROME, headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900 });
    page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));

    // --- Weather page, live search ---
    await page.goto(BASE + '/app?fresh=1#/weather', { waitUntil: 'networkidle0' });
    await page.evaluate(() => { const c = document.querySelector('#w-demo'); if (c) c.checked = false; });
    await page.type('#w-location', 'Jaipur');
    await page.click('#weatherForm button[type="submit"]');
    await page.waitForFunction(
      () => document.querySelector('#weatherBody .badge--live, #weatherBody .banner--demo'),
      { timeout: 20000 });
    const weatherLive = await page.evaluate(() => {
      const live = !!document.querySelector('#weatherBody .badge--live');
      const demo = !!document.querySelector('#weatherBody .banner--demo');
      const loc = (document.querySelector('#weatherBody .badge--outline') || {}).textContent || '';
      return { live, demo, loc: loc.trim() };
    });
    console.log('Weather page live search ->', JSON.stringify(weatherLive));
    await page.screenshot({ path: path.join(ROOT, 'shots', '12-weather-live-true.png'), fullPage: true });

    // --- Analysis form, live location, demo off ---
    await page.goto(BASE + '/app?fresh=2#/analysis', { waitUntil: 'networkidle0' });
    await page.evaluate(() => {
      const d = document.querySelector('#demoToggle'); if (d) d.checked = false;
      const s = document.querySelector('#scenarioSelect'); if (s) s.value = '';
    });
    await page.type('#f-location', 'Nagpur');
    await page.select('#f-crop', 'cotton');
    await page.select('#f-stage', 'flowering');
    await page.select('#f-soil', 'black');
    await page.select('#f-method', 'drip');
    await page.evaluate(() => { document.querySelector('#f-area').value = '1.5'; });
    await page.evaluate(() => { document.querySelector('#f-water').value = '120000'; });
    await page.click('#analyseBtn');
    await page.waitForFunction(
      () => { const v = document.querySelector('#view-results');
        return v && !v.hidden && document.querySelector('#resultsBody .rec-banner'); },
      { timeout: 25000 });
    const analysisLive = await page.evaluate(() => {
      const demo = !!document.querySelector('#resultsBody .banner--demo');
      const live = !!document.querySelector('#resultsBody .badge--live');
      const status = (document.querySelector('#resultsBody .rec-banner__status') || {}).textContent || '';
      const value = (document.querySelector('#resultsBody .rec-banner__value b') || {}).textContent || '';
      return { live, demo, status: status.trim(), value: value.trim() };
    });
    console.log('Analysis live submit ->', JSON.stringify(analysisLive));
    await page.screenshot({ path: path.join(ROOT, 'shots', '13-analysis-live.png'), fullPage: true });
  } catch (err) {
    console.log('DRIVER ERROR: ' + err.message);
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
  }
  console.log('page errors: ' + (errors.length ? errors.join(' | ') : 'none'));
})();
