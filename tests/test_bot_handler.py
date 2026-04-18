import pytest
from src.bot_handler import _is_allowed


class TestIsAllowed:
    def test_empty_list_allows_all(self):
        assert _is_allowed(12345, []) is True

    def test_user_in_list(self):
        assert _is_allowed(111, [111, 222]) is True

    def test_user_not_in_list(self):
        assert _is_allowed(333, [111, 222]) is False
