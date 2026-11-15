# Build targets for Riyaz.
#
# Usage:
#   make setup            # project-local Python 3.12 + .venv (first time)
#   make vendor           # download Tone.js and piano samples into static/ (about 2.3 MB)
#   make run              # open the app window
#   make test             # run the tests
#   make fake             # play a tune on the virtual keyboard port
#   make latency          # measure key-to-app delay (app must run)
#   make build-mac        # build dist/Riyaz.app (with the audio import, about 290 MB)
#   make build-mac-base   # build dist/Riyaz.app without the audio import (about 45 MB)
#   make release-mac VERSION=v0.1.0   # build and publish a GitHub release (macOS)
#   make clean            # remove build output
#   make distclean        # remove build output, .venv and all downloads (.cache, vendor-downloads)
#
# Everything stays inside this folder: these exports keep uv, Python and PyInstaller local.
# env.sh has the same values for a manual shell (". ./env.sh").

ROOT := $(CURDIR)
export UV_CACHE_DIR := $(ROOT)/.cache/uv
export UV_PYTHON_INSTALL_DIR := $(ROOT)/.cache/python
export UV_PYTHON_PREFERENCE := only-managed
export UV_PYTHON_DOWNLOADS := manual
export PYINSTALLER_CONFIG_DIR := $(ROOT)/.cache/pyinstaller

PYI := uv run pyinstaller
NAME := Riyaz
ARCH := $(shell uname -m)

TONE_VERSION := 15.1.22
TONE_URL := https://cdn.jsdelivr.net/npm/tone@$(TONE_VERSION)/build/Tone.js
SAMPLES_URL := https://tonejs.github.io/audio/salamander
SAMPLES := $(foreach o,1 2 3 4 5 6 7,$(foreach n,A C Ds Fs,$(n)$(o).mp3)) C8.mp3

.PHONY: setup vendor run test fake latency build-mac build-mac-base build-mac-ci release-mac clean distclean

setup:
	uv python install 3.12
	uv sync

# Downloads go to vendor-downloads/ first, then get copied into static/.
vendor:
	mkdir -p vendor-downloads/tone vendor-downloads/salamander static/vendor static/samples/salamander
	curl -fsSL -o vendor-downloads/tone/Tone.js "$(TONE_URL)"
	for f in $(SAMPLES); do curl -fsSL -o "vendor-downloads/salamander/$$f" "$(SAMPLES_URL)/$$f"; done
	cp vendor-downloads/tone/Tone.js static/vendor/tone.min.js
	cp vendor-downloads/salamander/*.mp3 static/samples/salamander/

run:
	uv run main.py

test:
	uv run pytest

fake:
	uv run tools/fake_player.py --repeat 0

latency:
	uv run tools/measure_latency.py

build-mac:
	$(PYI) --noconfirm Riyaz.spec

build-mac-base:
	RIYAZ_AUDIO=0 $(PYI) --noconfirm Riyaz.spec

build-mac-ci: build-mac
	ditto -c -k --sequesterRsrc --keepParent "dist/$(NAME).app" "$(NAME)-macOS-$(ARCH).zip"

# Builds on this Mac and uploads to GitHub Releases with the gh CLI (Phase 6).
release-mac:
	@test -n "$(VERSION)" || (echo "Usage: make release-mac VERSION=v0.1.0" && exit 1)
	rm -rf build/ dist/ "$(NAME)-macOS-$(ARCH).zip"
	$(MAKE) build-mac-ci
	gh release create "$(VERSION)" "$(NAME)-macOS-$(ARCH).zip" --title "$(VERSION)" --generate-notes

clean:
	rm -rf build/ dist/ "$(NAME)-macOS-$(ARCH).zip" .pytest_cache
	find . -name __pycache__ -not -path "./.venv/*" -not -path "./.cache/*" -prune -exec rm -rf {} +

distclean: clean
	rm -rf .venv .cache vendor-downloads
