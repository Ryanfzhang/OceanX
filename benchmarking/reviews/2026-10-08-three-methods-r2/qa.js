const fs = require('fs');
const path = require('path');
const { chromium } = require('/Users/ryanzhang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = __dirname;
const previews = '/Users/ryanzhang/.codex/visualizations/2026/08/22/01a02889-8101-7d21-9d67-f7b62e1a6809/benchmark-review-20261008-r2';

(async () => {
  const scores = JSON.parse(fs.readFileSync(path.join(root, 'scores.json'))).queries;
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'figure-manifest.json')));
  for (const item of manifest) {
    const file = path.resolve(root, item.target);
    if (!fs.existsSync(file)) throw new Error('Missing figure: ' + file);
    const hash = require('crypto').createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    if (hash !== item.sha256) throw new Error('Changed figure: ' + file);
  }
  const browser = await chromium.launch({ headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const results = [];
  try {
    for (const lang of ['en', 'zh']) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, deviceScaleFactor: 1 });
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto('file://' + path.join(root, `review-${lang}.html`), { waitUntil: 'load' });
      await page.screenshot({ path: path.join(previews, `qa-${lang}-header.png`) });
      for (const id of ['updates', 'Q24', 'Q25', 'Q27', 'summary']) {
        await page.locator('#' + id).evaluate(e => window.scrollTo(0, e.offsetTop - 65));
        await page.screenshot({ path: path.join(previews, `qa-${lang}-${id}.png`) });
      }
      const stats = await page.evaluate(() => ({
        queries: document.querySelectorAll('section.query').length,
        methods: document.querySelectorAll('article.method').length,
        scoreRows: document.querySelectorAll('[data-summary-query]').length,
        chartBars: document.querySelectorAll('svg rect').length,
        images: document.images.length,
        overflow: document.documentElement.scrollWidth > innerWidth,
        brokenVisible: [...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.src),
        updateRows: document.querySelectorAll('#updates tbody tr').length,
      }));
      for (const row of await page.locator('[data-summary-query]').evaluateAll(es => es.map(e => ({ q: e.dataset.summaryQuery, m: e.dataset.summaryMethod, s: Number(e.dataset.score) })))) {
        if (scores[row.q].methods[row.m].score !== row.s) throw new Error('Summary score mismatch');
      }
      for (const bar of await page.locator('svg rect').evaluateAll(es => es.map(e => ({ q: e.dataset.query, m: e.dataset.method, s: Number(e.dataset.score) })))) {
        if (scores[bar.q].methods[bar.m].score !== bar.s) throw new Error('Bar score mismatch');
      }
      if (stats.queries !== 17 || stats.methods !== 51 || stats.scoreRows !== 51 || stats.chartBars !== 51 || stats.images !== manifest.length || stats.updateRows !== 5 || stats.overflow || stats.brokenVisible.length || errors.length) {
        throw new Error(JSON.stringify({ stats, errors }));
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.locator('#updates').evaluate(e => window.scrollTo(0, e.offsetTop - 65));
      await page.screenshot({ path: path.join(previews, `qa-${lang}-mobile.png`) });
      const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (mobileOverflow) throw new Error('Mobile body overflow');
      results.push({ lang, ...stats, mobileOverflow, errors });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(root, 'qa.json'), JSON.stringify(results, null, 2) + '\n');
  console.log(JSON.stringify(results, null, 2));
})().catch(e => { console.error(e); process.exit(1); });
