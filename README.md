# FP course website

Organization website: https://fpcourse-materials.github.io/. The portal uses Quarto and GitHub Pages, with Russian course pages, full-text search of the portal, and downloadable teaching materials.

## Build and preview

Install Quarto 1.10.18 and Python 3.11 or newer. Imported public materials are committed in `materials/`, so building the portal needs no credentials or access to private repositories.

```sh
make build check
make preview
```

The complete publication is in `out/site/`. `make screenshots` checks desktop and mobile pages using the existing slides repository's Playwright and system Chromium; override `SLIDES` and `CHROME` when needed. Generated slides and PDFs are linked resources; portal search indexes the course descriptions, topics, and homework pages, not the full contents of those files.

After deployment, `make live-check` verifies the public portal and search index, then compares representative slide, exercise, notes, and archive downloads against their recorded checksums.

## Refresh teaching materials

The catalog in `materials.json` is the explicit publication list. Sources remain in their original repositories. Import only the catalog's approved student artifacts; the import never copies source repositories, teacher notes, quiz keys, screenshots, or solution branches. The source checkout can contain working changes: these are identified in `publication.json` alongside source revisions and SHA-256 checksums of every published file.

```sh
make import SLIDES=../slides DOCS=../../docs
make build check
make screenshots
```

The slides import rebuilds selected decks through `make public` and requires the slide repository's normal dependencies (`make setup` there). The catalog selects `publish.html`, `publish-pauses.html`, `publish.pdf`, and practice exercise sheets. Archive PDFs and FP2 notes are imported from the docs checkout as existing exports; rebuild those in their source repository when updating them.

Add a lesson, PDF, or public homework template to `materials.json`, import, build, and commit the reviewed changes. Pushing to `main` runs `.github/workflows/pages.yml` and deploys the whole site. Pull requests build and verify without deploying. `workflow_dispatch` also allows a manual redeploy. The initial publication uses local exports because the source slides repository is private; a later cross-repository build can replace imports once a narrowly scoped source-read credential is configured.

## GitHub Pages setup

The repository must be named `fpcourse-materials.github.io` inside `fpcourse-materials`, with Pages configured to use GitHub Actions. No custom domain is required. The deployment includes only the generated `out/site/` directory.

## Layout

- `pages/`: authored Quarto pages.
- `materials.json`: lesson metadata, publication formats, archive exports, and public homework links.
- `materials/`: selected public HTML and PDF exports.
- `publication.json`: imported source revisions and export checksums.
- `tools/site.py`: import, catalog generation, and link/integrity verification.
- `tools/inspect.mjs`: browser checks and screenshots.
- `out/project/`: assembled Quarto project; `out/site/`: rendered deployment.
