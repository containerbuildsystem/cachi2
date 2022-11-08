import textwrap
from typing import ClassVar, Optional


class Cachi2Error(Exception):
    """Root of the error hierarchy. Don't raise this directly, use more specific error types."""

    is_invalid_usage: ClassVar[bool] = False

    def friendly_msg(self) -> str:
        """Return the user-friendly representation of this error."""
        return str(self)


class InvalidInput(Cachi2Error):
    """User input was invalid."""

    is_invalid_usage: ClassVar[bool] = True


class PackageRejected(Cachi2Error):
    """Cachi2 refused to process the package the user requested.

    a) The package appears invalid (e.g. missing go.mod for a Go module).
    b) The package does not meet Cachi2's extra requirements (e.g. missing checksums).
    """

    is_invalid_usage: ClassVar[bool] = True

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


class UnsupportedFeature(Cachi2Error):
    """Cachi2 doesn't support a feature the user requested.

    The requested feature might be valid, but Cachi2 doesn't implement it.
    """

    is_invalid_usage: ClassVar[bool] = True
    default_solution = "If you need Cachi2 to support this feature, please contact the maintainers."

    def __init__(
        self, reason: str, *, solution: Optional[str] = default_solution, docs: Optional[str] = None
    ) -> None:
        """Initialize an Unsupported Feature error.

        :param reason: explain why the feature is not supported
        :param solution: politely suggest a potential solution (or workaround) to the user
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

    please_retry = (
        "The error might be intermittent, please try again.\n"
        "If the issue seems to be on the Cachi2 side, please contact the maintainers."
    )

    def friendly_msg(self) -> str:
        """Return the user-friendly representation of this error."""
        return _friendly_error_msg(str(self), self.please_retry)


class GoModError(Cachi2Error):
    """The 'go' command used while processing a Go module returned an error.

    Maybe the module is invalid, maybe the go tool was unable to fetch a dependency, maybe the
    error is intermittent. We don't really know, but we do at least log the stderr.
    """

    notice = textwrap.dedent(
        """
        The cause of the failure could be:
        - something is broken in Cachi2
        - something is wrong with your Go module
        - communication with an external service failed (please try again)
        The output of the failing go command should provide more details, please check the logs.
        """
    ).strip()

    def friendly_msg(self) -> str:
        """Return the user-friendly representation of this error."""
        return _friendly_error_msg(str(self), self.notice)


def _friendly_error_msg(
    reason: str, solution: Optional[str], docs_link: Optional[str] = None
) -> str:
    msg = reason
    if solution:
        msg += f"\n{textwrap.indent(solution, prefix='  ')}"
    if docs_link:
        msg += f"\n  Docs: {docs_link}"
    return msg
