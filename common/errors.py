class BrokenVaultError(Exception):
    """Expected application error with a stable error code."""

    def __init__(self, message: str, code: str = "ERROR") -> None:
        super().__init__(message)
        self.code = code


class RemoteError(BrokenVaultError):
    """An HTTP API request failed."""
