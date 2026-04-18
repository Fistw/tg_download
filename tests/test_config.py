import os
import tempfile

import pytest
import yaml

from src.config import (
    load_config,
    AppConfig,
    TelegramConfig,
    DownloadConfig,
    MonitorConfig,
    MonitorFilters,
    BotConfig,
)


class TestLoadConfigFromFile:
    def test_load_full_config(self, tmp_path):
        cfg_data = {
            "telegram": {
                "api_id": 99999,
                "api_hash": "test_hash",
                "bot_token": "test_token",
                "session_name": "my_session",
            },
            "download": {"output_dir": "/tmp/dl", "max_concurrent": 5},
            "monitor": {
                "channels": ["chan1", "chan2"],
                "filters": {
                    "min_size_mb": 10,
                    "max_size_mb": 2048,
                    "keywords": ["keyword1"],
                },
            },
            "bot": {"allowed_users": [111, 222]},
        }
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg_data))

        config = load_config(cfg_file)

        assert config.telegram.api_id == 99999
        assert config.telegram.api_hash == "test_hash"
        assert config.telegram.bot_token == "test_token"
        assert config.telegram.session_name == "my_session"
        assert config.download.output_dir == "/tmp/dl"
        assert config.download.max_concurrent == 5
        assert config.monitor.channels == ["chan1", "chan2"]
        assert config.monitor.filters.min_size_mb == 10
        assert config.monitor.filters.max_size_mb == 2048
        assert config.monitor.filters.keywords == ["keyword1"]
        assert config.bot.allowed_users == [111, 222]

    def test_load_missing_file_returns_defaults(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config.telegram.api_id == 0
        assert config.telegram.api_hash == ""
        assert config.download.output_dir == "./downloads"
        assert config.download.max_concurrent == 3
        assert config.monitor.channels == []
        assert config.bot.allowed_users == []

    def test_load_empty_file_returns_defaults(self, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("")
        config = load_config(cfg_file)
        assert config.telegram.api_id == 0

    def test_partial_config(self, tmp_path):
        cfg_data = {"telegram": {"api_id": 12345}}
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg_data))

        config = load_config(cfg_file)
        assert config.telegram.api_id == 12345
        assert config.telegram.api_hash == ""
        assert config.download.output_dir == "./downloads"


class TestMaxConcurrent:
    def test_max_concurrent_default(self, tmp_path):
        cfg_data = {"download": {"output_dir": "/tmp/dl"}}
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg_data))

        config = load_config(cfg_file)
        assert config.download.max_concurrent == 3

    def test_max_concurrent_custom(self, tmp_path):
        cfg_data = {"download": {"max_concurrent": 10}}
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg_data))

        config = load_config(cfg_file)
        assert config.download.max_concurrent == 10


class TestEnvOverride:
    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        cfg_data = {
            "telegram": {
                "api_id": 11111,
                "api_hash": "from_yaml",
                "bot_token": "from_yaml_token",
            }
        }
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump(cfg_data))

        monkeypatch.setenv("TG_API_ID", "99999")
        monkeypatch.setenv("TG_API_HASH", "from_env")
        monkeypatch.setenv("TG_BOT_TOKEN", "from_env_token")

        config = load_config(cfg_file)
        assert config.telegram.api_id == 99999
        assert config.telegram.api_hash == "from_env"
        assert config.telegram.bot_token == "from_env_token"

    def test_env_without_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TG_API_ID", "77777")
        monkeypatch.setenv("TG_API_HASH", "env_hash")

        config = load_config(tmp_path / "missing.yaml")
        assert config.telegram.api_id == 77777
        assert config.telegram.api_hash == "env_hash"
