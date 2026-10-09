# FP course website

Organization website: https://fpcourse-materials.github.io/. The portal uses Quarto and GitHub Pages, with Russian course pages, full-text search of the portal, and downloadable teaching materials.

URLs start with the year and course: `/2026/fp1/` and `/2026/fp2/`. Lesson pages and downloads share a directory, for example `/2026/fp1/practices/p04/` and `/2026/fp1/practices/p04/p04-publish.pdf`. The current publication includes FP1 practices P1–P5, FP2 lectures L1–L3, and the student FP2 notes with chapters 1–3. The 2025 archive and the full FP2 notes beyond chapter 3 are excluded.

Topic pages have a homework button next to their slide and PDF buttons when a student template is configured in the catalog. Homework IDs are scoped by course, so FP1 and FP2 assignments with the same number remain distinct. P4 links to the existing private student template and states that GitHub access is required. P5 links to the public FP1 homework 5 template. FP2 lectures L1–L3 link to their student homework repositories.

## Build and preview

Install Quarto 1.10.18 and Python 3.11 or newer. Imported public materials are committed in `materials/`, so building the portal needs no credentials or access to private repositories.

```sh
make build check
make preview
```

The complete publication is in `out/site/`. `make screenshots` checks desktop and mobile pages using the existing slides repository's Playwright and system Chromium; override `SLIDES` and `CHROME` when needed. Generated slides and PDFs are linked resources; portal search indexes the course descriptions, topics, and homework pages, not the full contents of those files.

After deployment, `make live-check` verifies the public portal and search index, compares representative downloads and every export of the latest FP1 practice against their recorded checksums, and confirms withdrawn materials return HTTP 404.

Use `make deploy-status` to list recent GitHub Pages workflow runs and `make deploy-wait RUN_ID=...` to wait for the selected deployment. These commands require an authenticated GitHub CLI (`gh`).

Publish reviewed changes with `make publish MSG="Publication description"`. This builds the site, checks links and checksums, verifies browser layouts, commits the publication, and pushes `main` to trigger GitHub Pages. After the deployment finishes, run `make live-check`.

The slide exports preserve Alt+Left/Right for browser Back/Forward; ordinary arrow keys still navigate slides. Imports apply `assets/browser-navigation.html` when the source export lacks it. `make fix-navigation build check` applies this fix to existing imported HTML and updates its checksums without rebuilding the material sources. The transformation is recorded in `publication.json`.

## Refresh teaching materials

The catalog in `materials.json` is the explicit publication list. Sources remain in their original repositories. Import only the catalog's approved student artifacts; the import never copies source repositories, teacher notes, quiz keys, screenshots, or solution branches. The source checkout can contain working changes: these are identified in `publication.json` alongside source revisions and SHA-256 checksums of every published file.

```sh
make import SLIDES=../slides DOCS=../../docs
make build check
make screenshots
```

The slides import rebuilds selected decks through `make public` and requires the slide repository's normal dependencies (`make setup` there). The catalog selects `publish.html`, `publish-pauses.html`, `publish.pdf`, and practice exercise sheets. Selected FP2 notes are imported from the docs checkout as existing exports; rebuild those in their source repository when updating them.

Use `make import COURSE=fp2` to refresh only FP2 while retaining the existing FP1 exports. Use `make import COURSE=fp1 LESSON=p05` to rebuild and import only practice 5; all other exports are retained after their recorded checksums are verified. The importer verifies retained files against their recorded checksums and records each file's source version. Build the student notes with `make -C ../../docs fp2-students N=3 S=99 SS=99` before importing chapters 1–3.

For URL changes or removal of already imported materials, use `make sync-catalog build check`. This relocates the retained exports and removes excluded ones without rebuilding source checkouts, preserving their checksums and source provenance. Adding exports that have not been imported requires `make import`.

Add a lesson, PDF, or public homework template to `materials.json`, import, build, and commit the reviewed changes. Pushing to `main` runs `.github/workflows/pages.yml` and deploys the whole site. Pull requests build and verify without deploying. `workflow_dispatch` also allows a manual redeploy. The initial publication uses local exports because the source slides repository is private; a later cross-repository build can replace imports once a narrowly scoped source-read credential is configured.

## GitHub Pages setup

The repository must be named `fpcourse-materials.github.io` inside `fpcourse-materials`, with Pages configured to use GitHub Actions. No custom domain is required. The deployment includes only the generated `out/site/` directory.

## Layout

- `pages/`: authored Quarto pages.
- `materials.json`: year, lesson metadata, publication formats, selected notes, and public homework links.
- `materials/`: selected public HTML and PDF exports.
- `publication.json`: imported source revisions and export checksums.
- `tools/site.py`: import, catalog generation, and link/integrity verification.
- `tools/inspect.mjs`: browser checks and screenshots.
- `out/project/`: assembled Quarto project; `out/site/`: rendered deployment.
