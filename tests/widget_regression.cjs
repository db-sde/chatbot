// Run with Node and Playwright installed. All HTTP traffic is intercepted.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chromium', headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    let chatBody;
    const submissions = [];
    let failSave = true;
    const title = '<img src=x onerror="window.leadTitleExecuted=true">';
    await page.route('**/*', async route => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/widget.js') return route.fulfill({
        contentType: 'application/javascript',
        body: fs.readFileSync(path.join(__dirname, '../widget/widget.js'), 'utf8'),
      });
      if (pathname === '/widget/config') return route.fulfill({ json: {
        lead_capture: { lead_form_title: title, lead_form_description: 'Save your callback request' },
      } });
      if (pathname === '/api/session/history') return route.fulfill({ json: { messages: [], has_more: false } });
      if (pathname === '/chat') {
        chatBody = request.postDataJSON();
        return route.fulfill({ contentType: 'text/event-stream', body:
          'event: token\ndata: {"text":"Please share your contact details."}\n\n' +
          'event: final\ndata: {"lead_ask":true,"quick_replies":[]}\n\n',
        });
      }
      if (pathname === '/webhook/lead') {
        submissions.push(request.postDataJSON());
        return route.fulfill({ status: failSave ? 503 : 200, json: { ok: !failSave } });
      }
      if (pathname === '/colleges/nmims/online-mba') return route.fulfill({
        contentType: 'text/html', body: '<html><body><script src="/widget.js" data-site-key="degreebaba_dev"></script></body></html>',
      });
      return route.abort();
    });
    await page.goto('http://localhost:2323/colleges/nmims/online-mba');
    await page.locator('#degreebaba-ai-widget .bubble').click();
    await page.locator('#degreebaba-ai-widget .composer input').fill('Please call me');
    await page.locator('#degreebaba-ai-widget .send-btn').click();
    const form = page.locator('#degreebaba-ai-widget .lead-card');
    await form.waitFor();
    assert.equal(chatBody.page_pathname, '/colleges/nmims/online-mba');
    assert.equal(await form.locator('h4').textContent(), title);
    assert.equal(await form.locator('h4 img').count(), 0);
    assert.equal(await page.evaluate(() => window.leadTitleExecuted), undefined);
    await form.locator('input[name=name]').fill('Test Student');
    await form.locator('input[name=phone]').fill('9999999999');
    await form.locator('.lead-submit').click();
    await page.waitForFunction(() => document.querySelector('#degreebaba-ai-widget').shadowRoot.querySelector('.lead-card p').textContent.includes("couldn't save"));
    assert.equal(await form.locator('input[name=name]').inputValue(), 'Test Student');
    assert.equal(await form.locator('.lead-submit').isEnabled(), true);
    assert.equal((await form.textContent()).includes('has been saved'), false);
    failSave = false;
    await form.locator('.lead-submit').click();
    await page.waitForFunction(() => document.querySelector('#degreebaba-ai-widget').shadowRoot.querySelector('.lead-card p').textContent.includes('has been saved'));
    assert.equal(submissions.length, 2);
    assert.equal(submissions[0].submission_id, submissions[1].submission_id);
    assert.deepEqual(errors, []);
    console.log('Widget browser regression passed: pathname, escaped settings, failed-save retry, idempotency, confirmed success.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
