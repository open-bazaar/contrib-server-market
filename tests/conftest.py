from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    # Manager operation files add their own paths below this directory on Windows.
    home = tmp_path_factory.mktemp("case")
    monkeypatch.setenv("BCN_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home
