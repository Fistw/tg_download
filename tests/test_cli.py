import pytest
from src.cli import _build_parser


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

    def test_verbose_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["-v", "serve"])
        assert args.verbose is True

    def test_config_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["-c", "my.yaml", "serve"])
        assert args.config == "my.yaml"
