from typing import NamedTuple, Union


class FileLocator(NamedTuple):
    """Locator that handles file, portal and link protocols.

    Sample locator string:
    name@protocol:path-to-local-file-or-folder::locator=project-name%40workspace%3Apath
    """

    @classmethod
    def from_string(cls, locator: str) -> "FileLocator":
        """Parse a Locator from a string."""
        return NotImplemented

    def __str__(self) -> str:
        return NotImplemented


class HttpsLocator(NamedTuple):
    """Locator that handles remote files fetched by HTTPS.

    Sample locator string:
    name@https://domain.com/url/to/file.tar.gz
    """

    @classmethod
    def from_string(cls, locator: str) -> "HttpsLocator":
        """Parse a Locator from a string."""
        return NotImplemented

    def __str__(self) -> str:
        return NotImplemented


class NpmLocator(NamedTuple):
    """Locator that handles registry dependencies.

    Sample locator strings:
    name@npm:version
    @scope/name@npm:version
    """

    @property
    def is_scoped(self) -> bool:
        """Check if this package is scoped.

        A scoped package follows the naming format of @scope/name.
        """
        return NotImplemented

    def scope(self) -> str:
        """Return the scope of this package."""
        return NotImplemented

    @classmethod
    def from_string(cls, locator: str) -> "NpmLocator":
        """Parse a Locator from a string."""
        return NotImplemented

    def __str__(self) -> str:
        return NotImplemented


class PatchLocator(NamedTuple):
    """Locator that handles patched dependencies.

    Sample locator string:
    name@patch:patched-dependency@npm%3A0.0.1#./path/to/patch::version=1.0.0&hash=abc123&locator=package-name%40workspace%3A
    name@patch:patched-dependency@npm%3A0.0.1#built-in<compat/patch-name>::version=1.0.0&hash=abc123 (built-in patch)
    """

    @classmethod
    def from_string(cls, locator: str) -> "PatchLocator":
        """Parse a Locator from a string."""
        return NotImplemented

    def __str__(self) -> str:
        return NotImplemented


class WorkspaceLocator(NamedTuple):
    """Locator that handles workspace dependencies.

    Sample locator string:
    name@workspace:path/to/dir
    """

    @classmethod
    def from_string(cls, locator: str) -> "WorkspaceLocator":
        """Parse a Locator from a string."""
        return NotImplemented

    def __str__(self) -> str:
        return NotImplemented


Locator = Union[
    FileLocator,
    HttpsLocator,
    NpmLocator,
    PatchLocator,
    WorkspaceLocator,
]


def parse_locator(locator: str) -> Locator:
    """Parse a Locator object based on a locator string from the 'yarn info' command.

    :raises PackageRejected: if a locator can't be parsed, or if it contains an protocol that is
        not supported.
    """
    # we should raise a different type of error for unsparseable/unknown locators, and banned
    # locators (such as ones that resolve to a Git dependency or containing the exec protocol)
    return NotImplemented
