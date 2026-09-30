import pytest

from common.errors import BrokenVaultError
from common.paths import normalize_relative_path, safe_destination


def test_path_traversal_rejected(tmp_path):
    for value in ["../secret.txt", "../../secret.txt", "/absolute.txt", "a/../b"]:
        with pytest.raises(BrokenVaultError):
            normalize_relative_path(value)


def test_destination_cannot_escape(tmp_path):
    with pytest.raises(BrokenVaultError):
        safe_destination(tmp_path, "../outside.txt")
