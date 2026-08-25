from __future__ import annotations

from pathlib import Path

import pytest

from ai_repo_radar.config import RadarConfig
from ai_repo_radar.sample_data import SampleFixture, load_sample_fixture
from ai_repo_radar.storage import JsonDataStore


@pytest.fixture
def sample_fixture() -> SampleFixture:
    return load_sample_fixture()


@pytest.fixture
def radar_config() -> RadarConfig:
    return RadarConfig().validate()


@pytest.fixture
def data_store(tmp_path: Path) -> JsonDataStore:
    store = JsonDataStore(tmp_path / "data")
    store.initialize()
    return store
