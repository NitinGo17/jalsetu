/*
 * v2 verification: render the user-first build across languages and check the
 * assistant/photo panels, the big answer, and console errors.
 *   node scripts/shots_v2.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');
const puppeteer = require('/usr/lib/node_modules/puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const PORT = 8140;
const BASE = `http://127.0.0.1:${PORT}`;
const SHOTS = path.join(ROOT, 'shots-v2');
const CHROME = '/usr/local/bin/chromium-headless-shell';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function ping(url) {
  return new Promise((res) => {
    const rq = http.get(url, (r) => { r.resume(); res(r.statusCode === 200); });
    rq.on('error', () => res(false)); rq.setTimeout(1500, () => { rq.destroy(); res(false); });
  });
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const server = spawn('python', ['-m', 'uvicorn', 'backend.main:app', '--port', String(PORT)], { cwd: ROOT, stdio: 'ignore' });
  for (let i = 0; i < 60; i++) { if (await ping(BASE + '/api/health')) break; await sleep(500); }

  const errors = [];
  let browser;
  try {
    browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] });
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 950 });
    page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));

    await page.goto(BASE + '/', { waitUntil: 'networkidle0' });
    await sleep(600);
    await page.screenshot({ path: path.join(SHOTS, '01-landing.png'), fullPage: true });

    // Analysis with farmer units
    await page.goto(BASE + '/app?f=1#/analysis', { waitUntil: 'networkidle0' });
    await page.waitForFunction(() => document.querySelectorAll('#scenarioCards [data-scenario]').length >= 3, { timeout: 15000 });
    await page.screenshot({ path: path.join(SHOTS, '02-analysis-units.png'), fullPage: true });

    // Run dry scenario -> big answer
    await page.click('#scenarioCards [data-scenario="dry"]');
    await page.waitForFunction(() => { const v = document.querySelector('#view-results'); return v && !v.hidden && document.querySelector('.answer'); }, { timeout: 25000 });
    await sleep(500);
    await page.screenshot({ path: path.join(SHOTS, '03-result-en.png'), fullPage: true });

    // Switch to each language and capture the result page
    const langs = [['hi-IN', '04-result-hi.png'], ['ta-IN', '05-result-ta.png'], ['te-IN', '06-result-te.png'], ['bn-IN', '07-result-bn.png'], ['mr-IN', '08-result-mr.png']];
    for (const [code, file] of langs) {
      await page.select('#langSelect', code);
      await sleep(900);
      await page.screenshot({ path: path.join(SHOTS, file), fullPage: true });
    }

    // Ask page (assistant + photo) — Sarvam unconfigured, so should show clear notices
    await page.select('#langSelect', 'hi-IN');
    await sleep(400);
    await page.goto(BASE + '/app?f=2#/ask', { waitUntil: 'networkidle0' });
    await sleep(700);
    await page.screenshot({ path: path.join(SHOTS, '09-ask-hi.png'), fullPage: true });

    // Dashboard with a result, in English
    await page.select('#langSelect', 'en-IN');
    await sleep(400);
    await page.goto(BASE + '/app?f=3#/dashboard', { waitUntil: 'networkidle0' });
    await sleep(700);
    await page.screenshot({ path: path.join(SHOTS, '10-dashboard.png'), fullPage: true });

    // Mobile, Hindi
    await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });
    await page.select('#langSelect', 'hi-IN');
    await sleep(600);
    await page.goto(BASE + '/app?f=4#/results', { waitUntil: 'networkidle0' });
    await sleep(700);
    await page.screenshot({ path: path.join(SHOTS, '11-mobile-hi.png'), fullPage: true });

    console.log('shots-v2 written');
  } catch (err) {
    console.log('DRIVER ERROR: ' + err.message);
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
  }
  console.log('--- console/page errors (' + errors.length + ') ---');
  errors.slice(0, 25).forEach((e) => console.log(e));
  if (!errors.length) console.log('none');
})();
