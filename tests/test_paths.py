from pathlib import Path

from honestbt import paths


def _home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Documents").mkdir()
    return tmp_path / "Documents"


def test_new_folder_is_titanium(tmp_path, monkeypatch):
    docs = _home(tmp_path, monkeypatch)
    assert paths.app_dir() == docs / "Titanium"


def test_old_strategy_lab_folder_is_renamed_once(tmp_path, monkeypatch):
    docs = _home(tmp_path, monkeypatch)
    (docs / "Strategy Lab" / "plugins").mkdir(parents=True)
    (docs / "Strategy Lab" / "mine.json").write_text("{}")
    assert paths.app_dir() == docs / "Titanium"
    assert (docs / "Titanium" / "mine.json").exists()
    assert (docs / "Titanium" / "plugins").is_dir()
    assert not (docs / "Strategy Lab").exists()


def test_existing_titanium_folder_is_left_alone(tmp_path, monkeypatch):
    docs = _home(tmp_path, monkeypatch)
    (docs / "Strategy Lab").mkdir()
    (docs / "Titanium").mkdir()
    assert paths.app_dir() == docs / "Titanium"
    assert (docs / "Strategy Lab").exists()
