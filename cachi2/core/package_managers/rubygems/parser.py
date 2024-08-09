import logging
from typing import Optional, Union

import pydantic

from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)

GEMFILE_LOCK = "Gemfile.lock"


class GemMetadata(pydantic.BaseModel, extra="forbid"):
    """
    Base class for gem metadata.

    Attributes:
        name:       The name of the gem.
        version:    The version of the gem.
    """

    name: str
    version: str


class GemDependency(GemMetadata):
    """
    Represents a gem dependency.

    Attributes:
        source:     The source URL of the gem.
        checksum:   The checksum of the gem.
    """

    source: str
    checksum: Optional[str] = None


class GitDependency(GemMetadata):
    """
    Represents a git dependency.

    Attributes:
        url:        The URL of the git repository.
        revision:   Commit hash.
        branch:     The branch of the git repository.
    """

    url: str
    revision: str
    branch: Optional[str] = None


class PathDependency(GemMetadata):
    """
    Represents a path dependency.

    Attributes:
        path:       Subpath from package root.
    """

    path: str


BundlerDependency = Union[GemDependency, GitDependency, PathDependency]


def parse_gemlock(package_dir: RootedPath) -> list[BundlerDependency]:
    """TODO."""
    return NotImplemented


def _validate_gem_dependency(gem: GemDependency) -> None:
    """TODO."""


def _validate_path_dependency(package_dir: RootedPath, gem: PathDependency) -> None:
    """TODO."""


def _validate_git_dependency(gem: GitDependency) -> None:
    """TODO."""
