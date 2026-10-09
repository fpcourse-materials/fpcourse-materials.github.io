# make build       render the complete website into out/site/
# make import      rebuild selected materials; COURSE=fp1 LESSON=p05 refreshes one lesson
# make check       check every local link and every imported file's checksum
# make verify      build, check, and inspect desktop/mobile layouts
# make preview     serve the built website at http://127.0.0.1:8765
# make screenshots capture desktop/mobile previews (requires slides' Playwright)
# make clean       remove generated output, preserving imported materials
# make live-check  verify the deployed portal and representative downloads
# make sync-catalog relocate/remove existing exports to match the current catalog
# make fix-navigation preserve browser Back/Forward shortcuts in imported slides
# make deploy-status show the latest GitHub Pages workflow runs
# make deploy-wait RUN_ID=... wait for a selected deployment to finish
# make publish MSG="…" verify, commit the publication, and push to GitHub Pages
.DEFAULT_GOAL := build
QUARTO ?= quarto
PYTHON ?= python3
NODE ?= node
SLIDES ?= ../slides
DOCS ?= ../../docs
COURSE ?=
LESSON ?=
GH ?= gh
GITHUB_REPO ?= fpcourse-materials/fpcourse-materials.github.io
RUN_ID ?=
MSG ?=
PORT ?= 8765
CHROME ?= /usr/bin/chromium
export CHROME
SITE_CACHE ?= /tmp/fpcourse-site-cache
export XDG_CACHE_HOME := $(SITE_CACHE)
.PHONY: help import fix-navigation sync-catalog prepare build check verify preview screenshots clean live-check deploy-status deploy-wait
help:
	@sed -n '1,12p' Makefile | sed 's/^# //'
import:
	$(PYTHON) tools/site.py import --slides "$(SLIDES)" --docs "$(DOCS)" $(if $(COURSE),--course "$(COURSE)") $(if $(LESSON),--lesson "$(LESSON)")
fix-navigation:
	$(PYTHON) tools/site.py fix-navigation
sync-catalog:
	$(PYTHON) tools/site.py sync-catalog
prepare:
	$(PYTHON) tools/site.py prepare
build: prepare
	$(QUARTO) render out/project
check:
	$(PYTHON) tools/site.py check
live-check:
	$(PYTHON) tools/site.py live
deploy-status:
	$(GH) run list --repo "$(GITHUB_REPO)" --workflow pages.yml --limit 5 --json databaseId,status,conclusion,headSha,url
deploy-wait:
	@test -n "$(RUN_ID)" || { echo 'RUN_ID is required'; exit 1; }
	$(GH) run watch "$(RUN_ID)" --repo "$(GITHUB_REPO)" --interval 10 --exit-status
verify: build check screenshots
.PHONY: publish
publish: verify
	@test -n "$(MSG)" || { echo 'MSG is required'; exit 1; }
	@test "$$(git branch --show-current)" = main
	git diff --check
	git fetch origin main
	git merge-base --is-ancestor origin/main HEAD
	git add -A
	@if ! git diff --cached --quiet; then git commit -m "$(MSG)"; fi
	git push origin main:main
preview: build
	$(PYTHON) -m http.server $(PORT) --bind 127.0.0.1 --directory out/site
screenshots:
	$(NODE) tools/inspect.mjs "$(SLIDES)" "$(PORT)"
clean:
	rm -rf out .quarto
