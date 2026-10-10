/*
 * Visual + runtime verification: start the server, drive the real pages in
 * headless Chromium, capture console/page errors, and screenshot each view.
 *
 *   node scripts/shots.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');
const puppeteer = require('/usr/lib/node_modules/puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const PORT = 8138;
const BASE = `http://127.0.0.1:${PORT}`;
const SHOTS = path.join(ROOT, 'shots');
const CHROME = '/usr/local/bin/chromium-headless-shell';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function ping(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.setTimeout(1500, () => { req.destroy(); resolve(false); });
  });
}

async function waitForServer(proc) {
  for (let i = 0; i < 60; i++) {
    if (proc.exitCode !== null) throw new Error('server exited early');
    if (await ping(BASE + '/api/health')) return;
    await sleep(500);
  }
  throw new Error('server did not start');
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const server = spawn('python', ['-m', 'uvicorn', 'backend.main:app', '--port', String(PORT)],
    { cwd: ROOT, stdio: 'ignore' });

  const errors = [];
  let browser;
  try {
    await waitForServer(server);
    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
    page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
    page.on('requestfailed', (r) => errors.push('requestfailed: ' + r.url() + ' ' + (r.failure() && r.failure().errorText)));

    // 1. Landing
    await page.goto(BASE + '/', { waitUntil: 'networkidle0' });
    await page.screenshot({ path: path.join(SHOTS, '01-landing.png'), fullPage: true });

    // 2. App dashboard (empty state)
    await page.goto(BASE + '/app', { waitUntil: 'networkidle0' });
    await page.waitForFunction(() => document.querySelectorAll('[data-scenario]').length >= 3, { timeout: 15000 });
    await page.screenshot({ path: path.join(SHOTS, '02-dashboard-empty.png'), fullPage: true });

    // 3. New Analysis view
    await page.goto(BASE + '/app#/analysis', { waitUntil: 'networkidle0' });
    await sleep(600);
    await page.screenshot({ path: path.join(SHOTS, '03-analysis.png'), fullPage: true });

    // 4. Run the "dry" scenario -> results
    await page.goto(BASE + '/app#/analysis', { waitUntil: 'networkidle0' });
    await page.waitForFunction(() => document.querySelectorAll('#scenarioCards [data-scenario]').length >= 3, { timeout: 15000 });
    await page.click('#scenarioCards [data-scenario="dry"]');
    await page.waitForFunction(
      () => { const v = document.querySelector('#view-results');
        return v && !v.hidden && document.querySelector('#resultsBody .rec-banner'); },
      { timeout: 25000 });
    await sleep(400);
    await page.screenshot({ path: path.join(SHOTS, '04-results-dry.png'), fullPage: true });

    // 5. Run the "scarcity" scenario -> results
    await page.goto(BASE + '/app#/analysis', { waitUntil: 'networkidle0' });
    await page.waitForFunction(() => document.querySelectorAll('#scenarioCards [data-scenario]').length >= 3, { timeout: 15000 });
    await page.click('#scenarioCards [data-scenario="scarcity"]');
    await page.waitForFunction(
      () => { const v = document.querySelector('#view-results');
        return v && !v.hidden && document.querySelector('#resultsBody .rec-banner'); },
      { timeout: 25000 });
    await sleep(400);
    await page.screenshot({ path: path.join(SHOTS, '05-results-scarcity.png'), fullPage: true });

    // 6. My Fields
    await page.goto(BASE + '/app#/fields', { waitUntil: 'networkidle0' });
    await sleep(400);
    await page.click('#loadSamplesBtn');
    await sleep(4000);
    await page.screenshot({ path: path.join(SHOTS, '06-fields.png'), fullPage: true });

    // 7. Crop guide
    await page.goto(BASE + '/app#/crops', { waitUntil: 'networkidle0' });
    await page.waitForFunction(() => document.querySelectorAll('#cropsBody tbody tr').length > 5, { timeout: 10000 });
    await page.screenshot({ path: path.join(SHOTS, '07-crops.png'), fullPage: true });

    // 8. Weather (demo)
    await page.goto(BASE + '/app#/weather', { waitUntil: 'networkidle0' });
    await sleep(400);
    await page.click('#w-demo');
    await page.waitForFunction(() => document.querySelector('#weatherBody .data-table tbody tr'), { timeout: 15000 });
    await page.screenshot({ path: path.join(SHOTS, '08-weather-demo.png'), fullPage: true });

    // 9. Weather (live, built-in coordinates)
    await page.goto(BASE + '/app#/weather', { waitUntil: 'networkidle0' });
    await sleep(300);
    await page.type('#w-location', 'Nashik');
    await page.click('#weatherForm button[type="submit"]');
    await sleep(4000);
    await page.screenshot({ path: path.join(SHOTS, '09-weather-live.png'), fullPage: true });

    // 10. Settings
    await page.goto(BASE + '/app#/settings', { waitUntil: 'networkidle0' });
    await sleep(400);
    await page.screenshot({ path: path.join(SHOTS, '10-settings.png'), fullPage: true });

    // 11. Mobile
    await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });
    await page.goto(BASE + '/app#/dashboard', { waitUntil: 'networkidle0' });
    await sleep(600);
    await page.screenshot({ path: path.join(SHOTS, '11-mobile.png'), fullPage: true });

    console.log('Screenshots written to ' + SHOTS);
  } catch (err) {
    console.log('DRIVER ERROR: ' + err.message);
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
  }

  console.log('\n--- console/page errors (' + errors.length + ') ---');
  errors.slice(0, 30).forEach((e) => console.log(e));
  if (!errors.length) console.log('none');
})();
