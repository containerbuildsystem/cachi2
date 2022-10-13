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


class ValidationError(ValueError, Cachi2Error):
    """An error was encountered during validation."""


# Request error classifiers
class ClientError(Cachi2Error):
    """Client Error."""

    origin = RequestErrorOrigin.client


class ServerError(Cachi2Error):
    """Server Error."""

    origin = RequestErrorOrigin.server


# Web errors
class InvalidRequestData(ClientError):
    """Invalid request data."""

    pass


# Low-level errors
class FileAccessError(ServerError):
    """File not found."""

    pass


class SubprocessCallError(ServerError):
    """Error calling subprocess."""

    pass


class NetworkError(ServerError):
    """Network connection error."""

    pass


# Third-party service errors
class RepositoryAccessError(ServerError):
    """Repository is not accessible and can't be cloned."""

    pass


class GoModError(Cachi2Error):
    """Go mod related error. A module can't be downloaded by go mod download command."""

    pass


class UnsupportedFeature(ClientError):
    """Unsupported feature."""

    pass


class InvalidFileFormat(ClientError):
    """Invalid file format."""

    pass
