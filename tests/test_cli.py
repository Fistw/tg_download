import logging
import logging.handlers
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from src.cli import _build_parser, _setup_logging, _cleanup_old_logs
from src.config import AppConfig, LoggingConfig


class TestBuildParser:
    def test_download_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["download", "https://t.me/chan/1"])
        assert args.command == "download"
        assert args.target == "https://t.me/chan/1"
        assert args.msg_range is None

    def test_download_with_range(self):
        parser = _build_parser()
        args = parser.parse_args(["download", "channel", "--range", "10-20"])
        assert args.command == "download"
        assert args.target == "channel"
        assert args.msg_range == "10-20"

    def test_download_with_output(self):
        parser = _build_parser()
        args = parser.parse_args(["download", "https://t.me/c/1/1", "-o", "/tmp/out"])
        assert args.output == "/tmp/out"

    def test_serve_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.no_bot is False
        assert args.no_monitor is False

    def test_serve_no_bot(self):
        parser = _build_parser()
        args = parser.parse_args(["serve", "--no-bot"])
        assert args.no_bot is True

    def test_serve_no_monitor(self):
        parser = _build_parser()
        args = parser.parse_args(["serve", "--no-monitor"])
        assert args.no_monitor is True

    def test_no_command_raises(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_verbose_flag_main(self):
        parser = _build_parser()
        args, _ = parser.parse_known_args(["-v", "serve"])
        assert args.verbose is True

    def test_config_flag_main(self):
        parser = _build_parser()
        args, _ = parser.parse_known_args(["-c", "my.yaml", "serve"])
        assert args.config == "my.yaml"


class TestSetupLogging:
    def test_console_handler_added_without_config(self):
        _setup_logging(verbose=False)
        logger = logging.getLogger()
        assert len(logger.handlers) > 0
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_console_log_level_verbose(self):
        _setup_logging(verbose=True)
        logger = logging.getLogger()
        assert logger.level == logging.DEBUG

    def test_console_log_level_normal(self):
        _setup_logging(verbose=False)
        logger = logging.getLogger()
        assert logger.level == logging.INFO

    def test_file_handler_added_with_config(self, tmp_path):
        log_dir = tmp_path / "logs"
        config = AppConfig(
            logging=LoggingConfig(
                log_dir=str(log_dir),
                max_file_size_mb=1,
                retention_days=7,
                filename="test.log"
            )
        )
        _setup_logging(verbose=False, config=config)
        logger = logging.getLogger()
        assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers)
        assert log_dir.exists()


class TestCleanupOldLogs:
    def test_cleanup_old_logs_deletes_old_files(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        
        old_file = log_dir / "old.log"
        old_file.touch()
        old_mtime = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(old_file, (old_mtime, old_mtime))
        
        new_file = log_dir / "new.log"
        new_file.touch()
        
        _cleanup_old_logs(log_dir, retention_days=7)
        
        assert not old_file.exists()
        assert new_file.exists()

    def test_cleanup_old_logs_ignores_non_log_files(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        
        log_file = log_dir / "test.log"
        log_file.touch()
        log_mtime = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(log_file, (log_mtime, log_mtime))
        
        non_log_file = log_dir / "test.txt"
        non_log_file.touch()
        non_log_mtime = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(non_log_file, (non_log_mtime, non_log_mtime))
        
        _cleanup_old_logs(log_dir, retention_days=7)
        
        assert not log_file.exists()
        assert non_log_file.exists()

    def test_cleanup_old_logs_keep_all_when_retention_long(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        
        for i in range(5):
            f = log_dir / f"test{i}.log"
            f.touch()
            f_mtime = (datetime.now() - timedelta(days=3 + i)).timestamp()
            os.utime(f, (f_mtime, f_mtime))
        
        _cleanup_old_logs(log_dir, retention_days=10)
        
        assert len(list(log_dir.glob("*.log*"))) == 5
