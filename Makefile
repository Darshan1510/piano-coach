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
#   make release-zip [VARIANT=full|base]   # build + dist/release/<zip> + <zip>.sha256 (no upload)
#   make release-mac VERSION=v0.1.0 [VARIANT=full|base]   # release-zip, then show the gh command
#                                     (tools/release.sh; add RELEASE_YES=1 to really upload)
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

.PHONY: setup vendor run test fake latency build-mac build-mac-base build-mac-ci release-zip release-mac clean distclean

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

# Release (Phase 6, same flow as DocKit: build on this Mac, upload with the gh CLI).
# VARIANT=full: the app with the audio import (about 290 MB, Riyaz-macOS-arm64.zip).
# VARIANT=base: the app without it (about 45 MB, Riyaz-macOS-arm64-base.zip; install.sh --base).
# Which one is the default release file is an open choice for the user (DECISIONS.md "Phase 6").
VARIANT ?= full
RELEASE_DIR := dist/release
RELEASE_ZIP := $(NAME)-macOS-$(ARCH)$(if $(filter base,$(VARIANT)),-base,).zip

release-zip:
	@case "$(VARIANT)" in full|base) ;; *) echo "VARIANT must be full or base" && exit 1;; esac
	rm -rf build/ dist/
	$(MAKE) $(if $(filter base,$(VARIANT)),build-mac-base,build-mac)
	mkdir -p "$(RELEASE_DIR)"
	ditto -c -k --sequesterRsrc --keepParent "dist/$(NAME).app" "$(RELEASE_DIR)/$(RELEASE_ZIP)"
	cd "$(RELEASE_DIR)" && shasum -a 256 "$(RELEASE_ZIP)" > "$(RELEASE_ZIP).sha256"
	@echo "Release files:" && ls -lh "$(RELEASE_DIR)"

# tools/release.sh only prints the gh command, unless RELEASE_YES=1 (then it uploads).
release-mac:
	@test -n "$(VERSION)" || (echo "Usage: make release-mac VERSION=v0.1.0 [VARIANT=full|base]" && exit 1)
	$(MAKE) release-zip VARIANT=$(VARIANT)
	sh tools/release.sh "$(VERSION)" "$(RELEASE_DIR)/$(RELEASE_ZIP)" "$(RELEASE_DIR)/$(RELEASE_ZIP).sha256"

clean:
	rm -rf build/ dist/ "$(NAME)-macOS-$(ARCH).zip" .pytest_cache
	find . -name __pycache__ -not -path "./.venv/*" -not -path "./.cache/*" -prune -exec rm -rf {} +

distclean: clean
	rm -rf .venv .cache vendor-downloads
