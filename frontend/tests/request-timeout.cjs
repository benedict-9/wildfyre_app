// Regression: a legitimate multi-provider snapshot must survive 25 seconds.
// Uses the real browser app with virtual time; does not wait a real minute.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const sample = {fires:[], occurrences:[], wildlife_zones:[], mode:'sample', fetched_at:'2026-10-17T01:02:03Z', truncated:false};

(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    async function pendingRisk() {
      const page = await browser.newPage();
      let pending;
      let received;
      const arrived = new Promise(resolve => { received = resolve; });
      await page.clock.install();
      // Map assets are deliberately blocked: these tests isolate the API deadline.
      await page.route('https://unpkg.com/**', route => route.abort());
      await page.route('http://wf05.test/**', route => {
        const pathname = new URL(route.request().url()).pathname;
        if (pathname === '/config.js') {
          return route.fulfill({contentType:'text/javascript', body:'window.WILDFYRE_CONFIG={apiBaseUrl:"http://wf05-api.test"};'});
        }
        const file = path.join(root, pathname === '/' ? 'index.html' : pathname);
        return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html', body:fs.readFileSync(file)});
      });
      await page.route('http://wf05-api.test/risk', route => {
        pending = route;
        received();
      });
      await page.goto('http://wf05.test/');
      await arrived;
      return {page, pending};
    }

    const slow = await pendingRisk();
    try {
      await slow.page.clock.fastForward(26000);
      assert.match(await slow.page.locator('#data-status').innerText(), /Loading/, 'valid risk request must still be pending after 26 seconds');
      await slow.page.clock.fastForward(34000);
      assert.match(await slow.page.locator('#data-status').innerText(), /Loading/, 'four-provider request budget must allow a response at 60 seconds');
      await slow.pending.fulfill({status:200, contentType:'application/json', headers:{'Access-Control-Allow-Origin':'*'}, body:JSON.stringify(sample)});
      await slow.page.waitForFunction(() => document.getElementById('data-status').textContent.includes('Sample data'));
      assert.match(await slow.page.locator('#empty-state').innerText(), /No fire detections/);
      console.log('PASS: /risk pending at 26s and 60s renders a successful snapshot when fulfilled.');
    } finally {
      await slow.page.close();
    }

    const stalled = await pendingRisk();
    try {
      await stalled.page.clock.fastForward(74000);
      assert.match(await stalled.page.locator('#data-status').innerText(), /Loading/);
      await stalled.page.clock.fastForward(2000);
      await stalled.page.waitForFunction(() => document.getElementById('data-status').textContent.includes('Unable to load'));
      assert.equal(await stalled.page.locator('#refresh').isDisabled(), false);
      console.log('PASS: stalled /risk is bounded and retryable after the 75s deadline.');
    } finally {
      await stalled.page.close();
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
