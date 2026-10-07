import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { mkdirSync, readFileSync } from 'node:fs';
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
  const catalog = JSON.parse(readFileSync('materials.json', 'utf8'));
  const practice = catalog.lessons.filter(x => x.course === 'fp1').at(-1);
  const lessonPath = lesson => `/${catalog.year}/${lesson.course}/${lesson.kind}/${lesson.id}/`;
  const pages = ['/', `/${catalog.year}/`, `/${catalog.year}/fp1/`, lessonPath(practice), `/${catalog.year}/fp2/`, lessonPath(catalog.lessons.at(-1))];
  const homework = new Map(catalog.homework.map(item => [`${item.course}/${item.id}`, item]));
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
    await page.locator('.aa-Input').fill(practice.title);
    await page.locator('.aa-Item').first().waitFor();
    if (!(await page.locator('.aa-Panel').innerText()).includes(practice.title)) errors.push(`${name}: search returned no lesson`);
    await page.close();
  }
  const deck = await browser.newPage();
  // Each topic has the homework for its own course; indexes contain no homework list.
  for (const lesson of catalog.lessons) {
    await deck.goto(`http://127.0.0.1:${port}${lessonPath(lesson)}`, { waitUntil: 'networkidle' });
    const hw = homework.get(`${lesson.course}/${lesson.homework}`);
    const button = deck.locator('.material-links a').filter({ hasText: 'Домашнее задание' });
    if (!lesson.homework) {
      if (await button.count()) errors.push(`${lesson.course}/${lesson.id}: unexpected homework button`);
      continue;
    }
    if (!hw || await button.count() !== 1 || await button.getAttribute('href') !== hw.url) errors.push(`${lesson.course}/${lesson.id}: incorrect homework button`);
  }
  for (const course of ['fp1', 'fp2']) {
    await deck.goto(`http://127.0.0.1:${port}/${catalog.year}/${course}/`, { waitUntil: 'networkidle' });
    if (await deck.locator('a[href^="https://github.com/fpcourse-students/"]').count()) errors.push(`${course}: homework links should be on topic pages`);
  }
  for (const lesson of [practice, ...catalog.lessons.filter(x => x.course === 'fp2')]) {
    for (const mode of ['publish', 'publish-pauses']) {
      const topic = `http://127.0.0.1:${port}${lessonPath(lesson)}`;
      const slideURL = `${topic}${lesson.id}-${mode}.html`;
      await deck.goto(topic, { waitUntil: 'networkidle' });
      await deck.locator(`.material-links a[href$="${lesson.id}-${mode}.html"]`).click();
      await deck.waitForFunction(() => window.Reveal?.isReady());
      if (await deck.locator('aside.notes').count()) errors.push(`${mode}: speaker notes present`);
      if (await deck.locator('.math').count() && await deck.locator('.math:not(:has(.katex))').count()) errors.push(`${lesson.course}/${lesson.id}/${mode}: unrendered math`);
      await deck.evaluate(() => Reveal.slide(1));
      const before = await deck.evaluate(() => JSON.stringify(Reveal.getIndices()));
      await deck.keyboard.press('ArrowRight');
      if (await deck.evaluate(() => JSON.stringify(Reveal.getIndices())) === before) errors.push(`${mode}: ordinary ArrowRight no longer advances slides`);
      for (const [key, keyCode] of [['ArrowLeft', 37], ['ArrowRight', 39]]) {
        const result = await deck.evaluate(({key, keyCode}) => {
          const before = JSON.stringify(Reveal.getIndices());
          const event = new KeyboardEvent('keydown', { key, code: key, keyCode, which: keyCode, altKey: true, bubbles: true, cancelable: true });
          document.body.dispatchEvent(event);
          return { prevented: event.defaultPrevented, moved: before !== JSON.stringify(Reveal.getIndices()) };
        }, {key, keyCode});
        if (result.prevented || result.moved) errors.push(`${mode}: Reveal intercepts Alt+${key}`);
      }
      // Slide changes replace the hash; browser Back returns to the topic page.
      await deck.goBack({ waitUntil: 'networkidle' });
      if (deck.url() !== topic) errors.push(`${mode}: browser Back did not return to the topic`);
      await deck.goForward({ waitUntil: 'load' });
      if (!deck.url().startsWith(slideURL)) errors.push(`${mode}: browser Forward did not reopen slides`);
    }
  }
  if (errors.length) throw new Error(errors.join('\n'));
  console.log(`Desktop/mobile pages, search, configured homework buttons, FP1/FP2 slide arrow keys and browser Back/Forward verified; screenshots in out/screenshots/`);
} finally {
  if (browser) await browser.close();
  server.kill();
}
