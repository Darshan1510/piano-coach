"""Phase 6: install.sh with a LOCAL release zip (never a download, never /Applications or
~/Applications): the SHA-256 check, a bad checksum, the quarantine attribute (removed only from
the installed app), file:// URLs. The tests make a small stand-in Riyaz.app (a shell script)."""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
Q = "com.apple.quarantine"
QVAL = "0081;00000000;Safari;"

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="install.sh is for macOS (ditto, xattr)")


def _xattr(path: Path) -> str:
    return subprocess.run(["xattr", "-l", str(path)], capture_output=True, text=True).stdout


@pytest.fixture
def release(tmp_path):
    """dist/Riyaz-macOS-arm64.zip + .sha256 of a stand-in app with the quarantine attribute."""
    app = tmp_path / "build" / "Riyaz.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text("<plist><dict></dict></plist>")
    exe = macos / "Riyaz"
    exe.write_text("#!/bin/sh\necho riyaz-stand-in\n")
    exe.chmod(0o755)
    subprocess.run(["xattr", "-w", Q, QVAL, str(app)], check=True)
    subprocess.run(["xattr", "-w", Q, QVAL, str(exe)], check=True)
    out = tmp_path / "dist"
    out.mkdir()
    zip_ = out / "Riyaz-macOS-arm64.zip"
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(zip_)], check=True)
    # A downloaded zip has the quarantine attribute; ditto gives it to the files it unpacks.
    subprocess.run(["xattr", "-w", Q, QVAL, str(zip_)], check=True)
    digest = hashlib.sha256(zip_.read_bytes()).hexdigest()
    (out / "Riyaz-macOS-arm64.zip.sha256").write_text(f"{digest}  Riyaz-macOS-arm64.zip\n")
    return zip_, digest


def run(*args, cwd=None):
    return subprocess.run(["sh", str(INSTALL), "--no-open", *args], capture_output=True, text=True, cwd=cwd, timeout=60)


def test_install_from_a_local_zip_checks_and_removes_quarantine(release, tmp_path):
    zip_, _ = release
    dest = tmp_path / "Apps"
    dest.mkdir()
    other = dest / "Other.app"
    other.mkdir()
    subprocess.run(["xattr", "-w", Q, QVAL, str(other)], check=True)
    check = tmp_path / "check"
    subprocess.run(["ditto", "-x", "-k", str(zip_), str(check)], check=True)
    assert Q in _xattr(check / "Riyaz.app")  # the precondition: an unpacked app is quarantined
    r = run("--zip", str(zip_), "--dest", str(dest))
    assert r.returncode == 0, r.stderr
    assert "Checksum OK" in r.stdout
    app = dest / "Riyaz.app"
    exe = app / "Contents" / "MacOS" / "Riyaz"
    assert subprocess.run([str(exe)], capture_output=True, text=True).stdout.strip() == "riyaz-stand-in"
    assert Q not in _xattr(app) and Q not in _xattr(exe)
    assert Q in _xattr(other)  # only the installed app is changed
    assert not (dest / ".Riyaz.app.new").exists()
    # A second install replaces the app.
    exe.write_text("old")
    r = run("--zip", f"file://{zip_}", "--dest", str(dest))
    assert r.returncode == 0, r.stderr
    assert exe.read_text().startswith("#!/bin/sh")


def test_bad_checksum_is_rejected(release, tmp_path):
    zip_, digest = release
    dest = tmp_path / "Apps"
    bad = "0" * 64
    r = run("--zip", str(zip_), "--sha256", bad, "--dest", str(dest))
    assert r.returncode == 1 and "checksum does not match" in r.stderr
    assert not (dest / "Riyaz.app").exists()
    # A changed zip with the old checksum file.
    with open(zip_, "ab") as f:
        f.write(b"x")
    r = run("--zip", str(zip_), "--dest", str(dest))
    assert r.returncode == 1 and "checksum does not match" in r.stderr and not (dest / "Riyaz.app").exists()
    # The right checksum of the changed zip, given as text: it installs.
    new = hashlib.sha256(zip_.read_bytes()).hexdigest()
    assert new != digest
    r = run("--zip", str(zip_), "--sha256", new.upper(), "--dest", str(dest))
    assert r.returncode == 0, r.stderr
    assert "Checksum OK" in r.stdout and (dest / "Riyaz.app").is_dir()


def test_missing_checksum_is_rejected(release, tmp_path):
    zip_, _ = release
    Path(str(zip_) + ".sha256").unlink()
    dest = tmp_path / "Apps"
    r = run("--zip", str(zip_), "--dest", str(dest))
    assert r.returncode == 1 and "No checksum" in r.stderr and not (dest / "Riyaz.app").exists()
    r = run("--zip", str(tmp_path / "nothing.zip"), "--dest", str(dest))
    assert r.returncode == 1 and "is not there" in r.stderr


def test_checksum_as_hex_and_default_dest_text(release, tmp_path):
    zip_, digest = release
    dest = tmp_path / "Apps with space"
    r = run("--zip", str(zip_), "--sha256", digest, "--dest", str(dest))
    assert r.returncode == 0, r.stderr
    assert (dest / "Riyaz.app").is_dir()
    src = INSTALL.read_text()
    assert 'INSTALL_DIR="$HOME/Applications"' in src and '--system) INSTALL_DIR="/Applications"' in src
    assert 'REPO="Darshan1510/piano-coach"' in src and "xattr -dr com.apple.quarantine \"$APP_PATH\"" in src
    assert "xattr -cr" not in src  # only the quarantine flag, only on the app


def test_help_works_through_a_pipe_and_main_runs_last():
    """curl | sh: --help prints the text (no "$0" file to read); a file cut in the middle runs nothing."""
    src = INSTALL.read_text()
    r = subprocess.run(["sh", "-s", "--", "--help"], input=src, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "Usage:" in r.stdout and "--sha256 FILE|HEX" in r.stdout
    assert '"$0"' not in src
    assert src.rstrip().splitlines()[-1] == 'main "$@"'
    assert "trap 'rm -rf \"$TMP_DIR\"; exit 130' INT TERM" in src and "trap 'rm -rf \"$TMP_DIR\"' EXIT" in src
    # A download that stops before the last line: the shell reads only function text, so nothing runs.
    cut = src[: src.rindex('main "$@"')]
    r = subprocess.run(["sh", "-s", "--", "--zip", "/nothing.zip"], input=cut, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    half = src[: src.index("main() {") + 400]
    r = subprocess.run(["sh", "-s", "--", "--help"], input=half, capture_output=True, text=True, timeout=30)
    assert "Usage:" not in r.stdout  # a cut function body is a syntax error, not a half run
    for sh in ("/bin/sh", "/bin/dash"):
        if Path(sh).exists():
            assert subprocess.run([sh, "-n", str(INSTALL)], capture_output=True).returncode == 0


def test_release_script_is_dry_by_default(release, tmp_path):
    zip_, _ = release
    sha = Path(str(zip_) + ".sha256")
    r = subprocess.run(["sh", str(ROOT / "tools" / "release.sh"), "v0.1.0", str(zip_), str(sha)],
                       capture_output=True, text=True, timeout=30, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0 and "Not uploaded" in r.stdout and "gh release create v0.1.0" in r.stdout
    with open(zip_, "ab") as f:
        f.write(b"x")
    r = subprocess.run(["sh", str(ROOT / "tools" / "release.sh"), "v0.1.0", str(zip_)],
                       capture_output=True, text=True, timeout=30, env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 1 and "does not match" in r.stderr
