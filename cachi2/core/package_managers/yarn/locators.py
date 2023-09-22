import re
from dataclasses import dataclass
from functools import cached_property
from typing import NamedTuple, Optional, Union
from urllib.parse import parse_qs, unquote

from cachi2.core.errors import UnexpectedFormat

# --- Locator types ---


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


# --- Parsing locators generically ---


# dataclass rather than NamedTuple because NamedTuple doesn't support cached_property
@dataclass(frozen=True)
class _ParsedLocator:
    scope: Optional[str]
    name: str
    raw_reference: str

    def __str__(self) -> str:
        name_at_ref = f"{self.name}@{self.raw_reference}"
        if self.scope:
            return f"@{self.scope}/{name_at_ref}"
        return name_at_ref

    @cached_property
    def parsed_reference(self) -> "_ParsedReference":
        return _parse_reference(self.raw_reference)


class _ParsedReference(NamedTuple):
    protocol: Optional[str]
    source: Optional[str]
    selector: str
    params: Optional[dict[str, list[str]]]


def _parse_locator(locator_str: str) -> _ParsedLocator:
    # https://github.com/yarnpkg/berry/blob/b6026842dfec4b012571b5982bb74420c7682a73/packages/yarnpkg-core/sources/structUtils.ts#L411
    locator_re = re.compile(r"^(?:@([^/]+?)/)?([^@/]+?)(?:@(.+))$")
    match = locator_re.match(locator_str)
    if not match:
        raise UnexpectedFormat("could not parse locator (expected [@scope/]name@reference)")
    scope, name, reference = match.groups()
    return _ParsedLocator(scope, name, reference)


def _parse_reference(reference_str: str) -> _ParsedReference:
    """Parse a reference string.

    [@scope/]name@reference
                  ^^^^^^^^^

    References follow these forms:

        <protocol>:<selector>::<bindings>
        <protocol>:<source>#<selector>::<bindings>

    See https://github.com/yarnpkg/berry/blob/b6026842dfec4b012571b5982bb74420c7682a73/packages/yarnpkg-core/sources/structUtils.ts#L452
    """
    reference_re = re.compile(r"^([^#:]*:)?((?:(?!::)[^#])*)(?:#((?:(?!::).)*))?(?:::(.*))?$")
    match = reference_re.match(reference_str)
    if not match:
        raise UnexpectedFormat("could not parse reference")

    groups = match.groups()
    has_source = bool(groups[2])  # <protocol>:<source>#<selector>::<bindings>
    # doesn't have source:          <protocol>:<selector>::<bindings>

    protocol = groups[0]
    source = unquote(groups[1]) if has_source else None
    selector = unquote(groups[2]) if has_source else unquote(groups[1])
    bindings = parse_qs(groups[3]) if groups[3] else None

    return _ParsedReference(
        protocol,
        source,
        selector,
        # For some reason, Yarnberry calls them bindings in the docstring but params in code
        params=bindings,
    )
