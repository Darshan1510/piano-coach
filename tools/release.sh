#!/bin/sh
# Publish a GitHub release of Riyaz with the gh CLI (Phase 6; same flow as DocKit's
# "make release-mac": build on this Mac, upload the zip).
#
#   sh tools/release.sh v0.1.0 dist/release/Riyaz-macOS-arm64.zip dist/release/Riyaz-macOS-arm64.zip.sha256
#
# Safe by default: the script checks the files and prints the gh command. It uploads only with
# RELEASE_YES=1. Before the upload: commit and push (the tag is made on GitHub from the default
# branch when it does not exist), and log in with "gh auth login".
# install.sh downloads <zip> and <zip>.sha256 from the release ("latest" or --version).

set -eu

VERSION="${1:?usage: tools/release.sh VERSION ZIP [ZIP.sha256 ...]}"
shift
[ $# -ge 1 ] || { echo "usage: tools/release.sh VERSION ZIP [ZIP.sha256 ...]" >&2; exit 2; }

case "$VERSION" in
    v[0-9]*) ;;
    *) echo "error: VERSION must look like v0.1.0" >&2; exit 2 ;;
esac

for f in "$@"; do
    [ -f "$f" ] || { echo "error: missing release file $f" >&2; exit 1; }
    case "$f" in
        *.zip)
            [ -f "$f.sha256" ] || { echo "error: missing checksum file $f.sha256 (make release-zip)" >&2; exit 1; }
            (cd "$(dirname "$f")" && shasum -a 256 -c "$(basename "$f").sha256") >/dev/null \
                || { echo "error: the checksum of $f does not match" >&2; exit 1; }
            ;;
    esac
done

FILES="$*"
set -- gh release create "$VERSION" "$@" --title "$VERSION" --generate-notes

if [ "${RELEASE_YES:-0}" != "1" ]; then
    echo "Release files are OK. Not uploaded. This is the upload command:"
    printf '  '
    printf '%s ' "$@"
    echo
    echo "To upload (after commit and push), run:"
    echo "  RELEASE_YES=1 sh tools/release.sh $VERSION $FILES"
    exit 0
fi

command -v gh >/dev/null 2>&1 || { echo "error: gh (GitHub CLI) is not installed" >&2; exit 1; }
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "error: the git folder has changes that are not committed" >&2
    exit 1
fi
exec "$@"
