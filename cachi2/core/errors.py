import textwrap
from typing import Optional


class Cachi2Error(Exception):
    """Root of the error hierarchy. Don't raise this directly, use more specific error types."""

    def friendly_msg(self) -> str:
        """Return the user-friendly representation of this error."""
        return str(self)


class PackageRejected(Cachi2Error):
    """Cachi2 refused to process the package the user requested.

    a) The package appears invalid (e.g. missing go.mod for a Go module).
    b) The package does not meet Cachi2's extra requirements (e.g. missing checksums).
    """

    def __init__(self, reason: str, *, solution: Optional[str], docs: Optional[str] = None) -> None:
        """Initialize a Package Rejected error.

        :param reason: explain why we rejected the package
        :param solution: politely suggest a potential solution to the user
        :param docs: include a link to relevant documentation (if there is any)
        """
        super().__init__(reason)
        self.solution = solution
        self.docs = docs

    def friendly_msg(self) -> str:
        """Return the user-friendly representation of this error."""
        return _friendly_error_msg(str(self), self.solution, self.docs)


class FetchError(Cachi2Error):
    """Cachi2 failed to fetch a dependency or other data needed to process a package."""


class GoModError(Cachi2Error):
    """The 'go' command used while processing a Go module returned an error.

    Maybe the module is invalid, maybe the go tool was unable to fetch a dependency, maybe the
    error is intermittent. We don't really know, but we do at least log the stderr.
    """


class UnsupportedFeature(Cachi2Error):
    """Cachi2 doesn't support a feature the user requested.

    The requested feature might be valid, but Cachi2 doesn't implement it.
    """


def _friendly_error_msg(reason: str, solution: Optional[str], docs_link: Optional[str]) -> str:
    msg = reason
    if solution:
        msg += f"\n{textwrap.indent(solution, prefix='  ')}"
    if docs_link:
        msg += f"\n  Docs: {docs_link}"
    return msg
