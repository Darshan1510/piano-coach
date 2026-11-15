#!/bin/sh
# Riyaz — macOS installer
#
# Downloads the latest release (Riyaz-macOS-arm64.zip and its .sha256 file) from GitHub,
# checks the SHA-256 checksum, installs Riyaz.app in ~/Applications (or /Applications with
# --system), removes the macOS quarantine attribute from the installed app only (the app is not
# signed, so Gatekeeper would block it), and opens it.
#
# Usage:
#   curl -LsSf https://raw.githubusercontent.com/Darshan1510/piano-coach/main/install.sh | sh
#   sh install.sh [options]
#
# Options:
#   --system          install in /Applications (default: ~/Applications)
#   --dest DIR        install in DIR (tests and checks)
#   --version vX.Y.Z  a release tag (default: the latest release)
#   --base            the base app without the audio import (smaller download)
#   --zip FILE|URL    use this release zip (a local file or a file:// URL), not a download
#   --sha256 FILE|HEX the checksum of --zip (default: FILE.sha256 next to the zip)
#   --no-open         do not open the app at the end
#
# If the GitHub repository is renamed, change REPO below (the only place it lives).

# The whole installer is in main(), called on the last line: a download that stops in the middle
# (curl | sh) runs nothing.

set -eu

say() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()  { printf '\033[1;32m✓\033[0m %s\n' "$1"; }
err() { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; }

# A file:// URL -> a path (spaces as %20 are common in copied URLs).
local_path() {
    case "$1" in
        file://*) printf '%s' "${1#file://}" | sed 's/%20/ /g' ;;
        *) printf '%s' "$1" ;;
    esac
}

usage() {
    cat <<'USAGE'
Riyaz - macOS installer

Downloads the latest release (Riyaz-macOS-arm64.zip and its .sha256 file) from GitHub,
checks the SHA-256 checksum, installs Riyaz.app in ~/Applications (or /Applications with
--system), removes the macOS quarantine attribute from the installed app only, and opens it.

Usage:
  curl -LsSf https://raw.githubusercontent.com/Darshan1510/piano-coach/main/install.sh | sh
  curl -LsSf https://raw.githubusercontent.com/Darshan1510/piano-coach/main/install.sh | sh -s -- --help
  sh install.sh [options]

Options:
  --system          install in /Applications (default: ~/Applications)
  --dest DIR        install in DIR (tests and checks)
  --version vX.Y.Z  a release tag (default: the latest release)
  --base            the base app without the audio import (smaller download)
  --zip FILE|URL    use this release zip (a local file or a file:// URL), not a download
  --sha256 FILE|HEX the checksum of --zip (default: FILE.sha256 next to the zip)
  --no-open         do not open the app at the end
  -h, --help        show this text
USAGE
}

main() {
    REPO="Darshan1510/piano-coach"
    APP_NAME="Riyaz"
    BUNDLE_ID="local.riyaz.app"
    INSTALL_DIR="$HOME/Applications"
    VERSION=""
    VARIANT=""
    ZIP_SRC=""
    SHA_SRC=""
    OPEN_APP=1

    while [ $# -gt 0 ]; do
        case "$1" in
            --system) INSTALL_DIR="/Applications" ;;
            --dest) shift; INSTALL_DIR="${1:?--dest needs a folder}" ;;
            --version) shift; VERSION="${1:?--version needs a tag}" ;;
            --base) VARIANT="-base" ;;
            --zip) shift; ZIP_SRC="${1:?--zip needs a file}" ;;
            --sha256) shift; SHA_SRC="${1:?--sha256 needs a file or a checksum}" ;;
            --no-open) OPEN_APP=0 ;;
            -h|--help) usage; exit 0 ;;
            *) err "Unknown option: $1"; exit 2 ;;
        esac
        shift
    done

    APP_PATH="$INSTALL_DIR/$APP_NAME.app"

    # --- preflight ---

    if [ "$(uname -s)" != "Darwin" ]; then
        err "This installer is for macOS only (detected: $(uname -s))."
        exit 1
    fi

    ARCH=$(uname -m)
    case "$ARCH" in
        arm64) ASSET="$APP_NAME-macOS-arm64$VARIANT.zip" ;;
        x86_64)
            err "Intel Macs are not supported. Only Apple Silicon (arm64) builds are published."
            exit 1
            ;;
        *) err "Unsupported architecture: $ARCH"; exit 1 ;;
    esac

    if [ -n "$VERSION" ]; then
        BASE_URL="https://github.com/$REPO/releases/download/$VERSION"
    else
        BASE_URL="https://github.com/$REPO/releases/latest/download"
    fi

    TMP_DIR=$(mktemp -d -t riyaz-install.XXXXXX)
    trap 'rm -rf "$TMP_DIR"' EXIT
    trap 'rm -rf "$TMP_DIR"; exit 130' INT TERM
    ZIP="$TMP_DIR/$ASSET"
    SUM="$TMP_DIR/$ASSET.sha256"

    # --- get the zip and the checksum ---

    if [ -n "$ZIP_SRC" ]; then
        SRC=$(local_path "$ZIP_SRC")
        if [ ! -f "$SRC" ]; then
            err "The file $SRC is not there."
            exit 1
        fi
        say "Using the local release file $SRC"
        cp "$SRC" "$ZIP"
        if [ -z "$SHA_SRC" ]; then
            SHA_SRC="$SRC.sha256"
        fi
    else
        say "Installing $APP_NAME for macOS ($ARCH)"
        say "Downloading $ASSET"
        if ! curl -fL --progress-bar -o "$ZIP" "$BASE_URL/$ASSET"; then
            err "Failed to download $BASE_URL/$ASSET"
            err "Check your internet connection, or visit https://github.com/$REPO/releases"
            exit 1
        fi
        if [ -z "$SHA_SRC" ]; then
            if ! curl -fsSL -o "$SUM" "$BASE_URL/$ASSET.sha256"; then
                err "Failed to download the checksum file $ASSET.sha256. The app is not installed."
                exit 1
            fi
        fi
    fi

    # --sha256 can be a file (shasum output: "<hex>  <name>") or the checksum itself.
    if [ -n "$SHA_SRC" ]; then
        S=$(local_path "$SHA_SRC")
        if [ -f "$S" ]; then
            cp "$S" "$SUM"
        elif printf '%s' "$S" | grep -Eq '^[0-9a-fA-F]{64}$'; then
            printf '%s  %s\n' "$S" "$ASSET" > "$SUM"
        else
            err "No checksum for the release file (expected $S). The app is not installed."
            exit 1
        fi
    fi

    # --- verify ---

    say "Checking the SHA-256 checksum"
    WANT=$(awk 'NR==1 {print tolower($1)}' "$SUM")
    GOT=$(shasum -a 256 "$ZIP" | awk '{print tolower($1)}')
    if ! printf '%s' "$WANT" | grep -Eq '^[0-9a-f]{64}$'; then
        err "The checksum file is not valid. The app is not installed."
        exit 1
    fi
    if [ "$WANT" != "$GOT" ]; then
        err "The checksum does not match. The download is damaged or changed. The app is not installed."
        err "  expected $WANT"
        err "  got      $GOT"
        exit 1
    fi
    ok "Checksum OK"

    # --- unpack ---

    say "Unpacking"
    if ! ditto -x -k "$ZIP" "$TMP_DIR/unpacked"; then
        err "Failed to unpack $ASSET"
        exit 1
    fi

    NEW_APP="$TMP_DIR/unpacked/$APP_NAME.app"
    if [ ! -d "$NEW_APP" ]; then
        err "Expected $APP_NAME.app in the release archive but did not find it."
        ls -la "$TMP_DIR/unpacked" >&2 || true
        exit 1
    fi

    # --- install ---

    if ! mkdir -p "$INSTALL_DIR"; then
        err "Could not create $INSTALL_DIR"
        exit 1
    fi

    # Quit a running Riyaz first, so that it closes the MIDI ports and is not deleted while open.
    if pgrep -f "$APP_PATH/Contents/MacOS/" >/dev/null 2>&1; then
        say "Quitting the running $APP_NAME"
        osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
        i=0
        while pgrep -f "$APP_PATH/Contents/MacOS/" >/dev/null 2>&1 && [ "$i" -lt 20 ]; do
            sleep 0.5
            i=$((i + 1))
        done
        if pgrep -f "$APP_PATH/Contents/MacOS/" >/dev/null 2>&1; then
            err "$APP_NAME is still running. Quit it, then run this installer again."
            exit 1
        fi
    fi

    # Move the new app next to the old one first, then swap (no half-installed app on an error).
    STAGE="$INSTALL_DIR/.$APP_NAME.app.new"
    rm -rf "$STAGE"
    mv "$NEW_APP" "$STAGE"
    if [ -e "$APP_PATH" ]; then
        say "Removing the old $APP_PATH"
        rm -rf "$APP_PATH"
    fi
    mv "$STAGE" "$APP_PATH"

    # --- strip quarantine (only on the installed app) ---

    say "Removing the quarantine attribute from $APP_PATH"
    xattr -dr com.apple.quarantine "$APP_PATH" 2>/dev/null || true

    ok "Installed to $APP_PATH"

    if [ "$OPEN_APP" -eq 1 ]; then
        say "Opening $APP_NAME"
        open "$APP_PATH"
    fi

    cat <<EOF

$APP_NAME is installed in $INSTALL_DIR.
Connect the keyboard (USB-MIDI cable), then open Setup in the app and click "Find my keyboard".
To update later, run this installer again. Your songs and progress stay in
~/Library/Application Support/$APP_NAME.
EOF
}

main "$@"
