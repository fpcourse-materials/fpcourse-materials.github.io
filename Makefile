# make build       render the complete website into out/site/
# make import      rebuild and import the catalog's selected teaching materials
# make check       check every local link and every imported file's checksum
# make verify      build, check, and inspect desktop/mobile layouts
# make preview     serve the built website at http://127.0.0.1:8765
# make screenshots capture desktop/mobile previews (requires slides' Playwright)
# make clean       remove generated output, preserving imported materials
# make live-check  verify the deployed portal and representative downloads
# make sync-catalog relocate/remove existing exports to match the current catalog
# make fix-navigation preserve browser Back/Forward shortcuts in imported slides
.DEFAULT_GOAL := build
QUARTO ?= quarto
PYTHON ?= python3
NODE ?= node
SLIDES ?= ../slides
DOCS ?= ../../docs
PORT ?= 8765
CHROME ?= /usr/bin/chromium
export CHROME
SITE_CACHE ?= /tmp/fpcourse-site-cache
export XDG_CACHE_HOME := $(SITE_CACHE)
.PHONY: help import fix-navigation sync-catalog prepare build check verify preview screenshots clean live-check
help:
	@sed -n '1,10p' Makefile | sed 's/^# //'
import:
	$(PYTHON) tools/site.py import --slides "$(SLIDES)" --docs "$(DOCS)"
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
verify: build check screenshots
preview: build
	$(PYTHON) -m http.server $(PORT) --bind 127.0.0.1 --directory out/site
screenshots:
	$(NODE) tools/inspect.mjs "$(SLIDES)" "$(PORT)"
clean:
	rm -rf out .quarto
