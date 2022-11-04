from enum import Enum


class Cachi2Error(Exception):
    """Root of the error hierarchy. Don't raise this directly, use more specific error types."""


class RequestErrorOrigin(str, Enum):
    """An Enum that represents the request error origin."""

    client = "client"
    server = "server"


class CachitoCalledProcessError(Cachi2Error):
    """Command executed with subprocess.run() returned non-zero value."""

    def __init__(self, err_msg: str, retcode: int):
        """Initialize the error with a message and the return code of the failing command."""
        super().__init__(err_msg)
        self.retcode = retcode


class PackageRejected(Cachi2Error):
    """Cachi2 refused to process the package the user requested.

    a) The package appears invalid (e.g. missing go.mod for a Go module).
    b) The package does not meet Cachi2's extra requirements (e.g. missing checksums).
    """


# Request error classifiers
class ClientError(Cachi2Error):
    """Client Error."""

    origin = RequestErrorOrigin.client


class ServerError(Cachi2Error):
    """Server Error."""

    origin = RequestErrorOrigin.server


class SubprocessCallError(ServerError):
    """Error calling subprocess."""

    pass


class FetchError(Cachi2Error):
    """Cachi2 failed to fetch a dependency or other data needed to process a package."""


class GoModError(Cachi2Error):
    """Go mod related error. A module can't be downloaded by go mod download command."""

    pass


class UnsupportedFeature(ClientError):
    """Unsupported feature."""

    pass
