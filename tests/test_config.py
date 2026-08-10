from pathlib import Path

import pytest
from pydantic import ValidationError

from wiki_updater.config import Settings


def test_local_mode_requires_loopback(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="loopback"):
        Settings(app_env="local", bind_host="0.0.0.0", data_dir=tmp_path)


def test_supported_languages_are_validated(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Unsupported language"):
        Settings(data_dir=tmp_path, enabled_languages=("en", "xx"))


def test_production_requires_oauth(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="OAuth"):
        Settings(app_env="production", bind_host="0.0.0.0", data_dir=tmp_path, session_secret="x" * 40)


def test_page_concurrency_is_bounded(tmp_path: Path) -> None:
    assert Settings(data_dir=tmp_path, page_concurrency=4).page_concurrency == 4
    with pytest.raises(ValidationError):
        Settings(data_dir=tmp_path, page_concurrency=5)
