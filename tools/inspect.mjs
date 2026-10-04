import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { mkdirSync } from 'node:fs';
import { spawn } from 'node:child_process';
const slides = resolve(process.argv[2] || '../slides');
const port = Number(process.argv[3] || 8765);
const require = createRequire(resolve(slides, 'package.json'));
const { chromium } = require('playwright-chromium');
mkdirSync('out/screenshots', { recursive: true });
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', 'out/site'], { stdio: ['ignore', 'ignore', 'pipe'] });
let serverError = '';
server.stderr.on('data', chunk => { serverError += chunk.toString(); });
let browser;
try {
  await new Promise((res, rej) => { server.once('error', rej); setTimeout(res, 600); });
  if (server.exitCode !== null) throw new Error(serverError);
  browser = await chromium.launch({ executablePath: process.env.CHROME || '/usr/bin/chromium' });
  const errors = [];
  const pages = ['/', '/fp1/2026/', '/fp1/2026/practices/p05/', '/fp2/2026/', '/archive/fp1-2025.html'];
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height } });
    page.on('pageerror', err => errors.push(err.message));
    page.on('response', res => { if (res.status() >= 400) errors.push(`${res.status()} ${res.url()}`); });
    for (let index = 0; index < pages.length; index++) {
      await page.goto(`http://127.0.0.1:${port}${pages[index]}`, { waitUntil: 'networkidle' });
      if (await page.locator('h1').count() !== 1) errors.push(`${name} ${pages[index]}: expected one main heading`);
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)) errors.push(`${name} ${pages[index]}: horizontal overflow`);
      await page.screenshot({ path: `out/screenshots/${name}-${index}.png`, fullPage: true });
    }
    // Exercise the search UI and confirm a current lesson appears in results.
    await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'networkidle' });
    await page.locator('#quarto-search button').click();
    await page.locator('.aa-Input').fill('Типы данных');
    await page.locator('.aa-Item').first().waitFor();
    if (!(await page.locator('.aa-Panel').innerText()).includes('Типы данных')) errors.push(`${name}: search returned no lesson`);
    await page.close();
  }
  const deck = await browser.newPage();
  for (const mode of ['publish', 'publish-pauses']) {
    await deck.goto(`http://127.0.0.1:${port}/materials/fp1/2026/practices/p05/p05-${mode}.html`, { waitUntil: 'load' });
    await deck.waitForFunction(() => window.Reveal?.isReady());
    if (await deck.locator('aside.notes').count()) errors.push(`${mode}: speaker notes present`);
    if (await deck.locator('.katex').count() === 0) errors.push(`${mode}: rendered math absent`);
  }
  if (errors.length) throw new Error(errors.join('\n'));
  console.log('Desktop/mobile pages, search, and both P5 slide formats verified; screenshots in out/screenshots/');
} finally {
  if (browser) await browser.close();
  server.kill();
}
