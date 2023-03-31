import textwrap
from typing import ClassVar, Optional

_argument_not_specified = "__argument_not_specified__"


class Cachi2Error(Exception):
    """Root of the error hierarchy. Don't raise this directly, use more specific error types."""

    is_invalid_usage: ClassVar[bool] = False
    default_solution: ClassVar[Optional[str]] = None

    def __init__(
        self,
        reason: str,
        *,
        solution: Optional[str] = _argument_not_specified,
        docs: Optional[str] = None,
    ) -> None:
        """Initialize a Cachi2 error.

        :param reason: explain what went wrong
        :param solution: politely suggest a potential solution to the user
        :param docs: include a link to relevant documentation (if there is any)
        """
        super().__init__(reason)
        if solution == _argument_not_specified:
            self.solution = self.default_solution
        else:
            self.solution = solution
        self.docs = docs

    def friendly_msg(self) -> str:
        """Return the user-friendly representation of this error."""
        msg = str(self)
        if self.solution:
            msg += f"\n{textwrap.indent(self.solution, prefix='  ')}"
        if self.docs:
            msg += f"\n  Docs: {self.docs}"
        return msg


class UsageError(Cachi2Error):
    """Generic error for "Cachi2 was used incorrectly." Prefer more specific errors."""

    is_invalid_usage: ClassVar[bool] = True


class InvalidInput(UsageError):
    """User input was invalid."""


class PackageRejected(UsageError):
    """Cachi2 refused to process the package the user requested.

    a) The package appears invalid (e.g. missing go.mod for a Go module).
    b) The package does not meet Cachi2's extra requirements (e.g. missing checksums).
    """

    def __init__(self, reason: str, *, solution: Optional[str], docs: Optional[str] = None) -> None:
        """Initialize a Package Rejected error.

        Compared to the parent class, the solution param is required (but can be explicitly None).

        :param reason: explain why we rejected the package
        :param solution: politely suggest a potential solution to the user
        :param docs: include a link to relevant documentation (if there is any)
        """
        super().__init__(reason, solution=solution, docs=docs)


class UnexpectedFormat(UsageError):
    """Cachi2 failed to parse a file in the user's package (e.g. requirements.txt)."""

    default_solution = (
        "Please check if the format of your file is correct.\n"
        "If yes, please let the maintainers know that Cachi2 doesn't handle it properly."
    )


class UnsupportedFeature(UsageError):
    """Cachi2 doesn't support a feature the user requested.

    The requested feature might be valid, but Cachi2 doesn't implement it.
    """

    default_solution = "If you need Cachi2 to support this feature, please contact the maintainers."


class FetchError(Cachi2Error):
    """Cachi2 failed to fetch a dependency or other data needed to process a package."""

    default_solution = (
        "The error might be intermittent, please try again.\n"
        "If the issue seems to be on the Cachi2 side, please contact the maintainers."
    )


class GoModError(Cachi2Error):
    """The 'go' command used while processing a Go module returned an error.

    Maybe the module is invalid, maybe the go tool was unable to fetch a dependency, maybe the
    error is intermittent. We don't really know, but we do at least log the stderr.
    """

    default_solution = textwrap.dedent(
        """
        The cause of the failure could be:
        - something is broken in Cachi2
        - something is wrong with your Go module
        - communication with an external service failed (please try again)
        The output of the failing go command should provide more details, please check the logs.
        """
    ).strip()
