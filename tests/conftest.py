import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Test data stays inside the project (.cache/ is in .gitignore) and is removed at the end.
# One folder per pytest process, so that 2 runs at the same time do not delete each other's files.
RUN_DIR = ROOT / ".cache" / "test-data" / f"run-{os.getpid()}"

# Never touch ~/Library/Application Support/Riyaz in tests.
if "RIYAZ_DATA_DIR" not in os.environ:
    os.environ["RIYAZ_DATA_DIR"] = str(RUN_DIR / "session")


def pytest_configure(config):
    # tmp_path also goes inside the project, not /var/folders.
    if config.option.basetemp is None:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(RUN_DIR / "tmp")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(RUN_DIR, ignore_errors=True)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RIYAZ_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def store(data_dir):
    from riyaz.db import Store

    s = Store()
    yield s
    s.close()
