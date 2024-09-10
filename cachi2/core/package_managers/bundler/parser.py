import json
import logging
import subprocess
from functools import cached_property
from pathlib import Path
from typing import Annotated, Optional, Union

import pydantic

from cachi2.core.errors import PackageManagerError, PackageRejected, UnexpectedFormat
from cachi2.core.package_managers.general import download_binary_file
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath
from cachi2.core.utils import run_cmd

log = logging.getLogger(__name__)

GEMFILE = "Gemfile"
GEMFILE_LOCK = "Gemfile.lock"

AcceptedUrl = Annotated[
    pydantic.HttpUrl,
    pydantic.UrlConstraints(allowed_schemes=["https"]),
]

AcceptedGitRef = Annotated[
    pydantic.StrictStr,
    pydantic.StringConstraints(pattern=r"^[a-fA-F0-9]{40}$"),
]


class _GemMetadata(pydantic.BaseModel):
    """
    Base class for gem metadata.

    Attributes:
        name:       The name of the gem.
        version:    The version of the gem.
    """

    name: str
    version: str

    def download_to(self, fs_location: RootedPath) -> None:
        return None


class GemDependency(_GemMetadata):
    """
    Represents a gem dependency.

    Attributes:
        source:     The source URL of the gem as stated in 'remote' field from Gemfile.lock.
        checksum:   The checksum of the gem.
    """

    source: str
    checksum: Optional[str] = None

    @cached_property
    def remote_location(self) -> str:
        """Return remote location to download this gem from."""
        return f"{self.source}/gems/{self.name}-{self.version}.gem"

    def download_to(self, fs_location: RootedPath) -> None:
        """Download represented gem to specified file system location."""
        fs_location = fs_location.join_within_root(Path(f"{self.name}-{self.version}.gem"))
        download_binary_file(self.remote_location, fs_location)


class GitDependency(_GemMetadata):
    """
    Represents a git dependency.

    Attributes:
        url:        The URL of the git repository.
        ref:        Commit hash.
    """

    url: AcceptedUrl
    ref: AcceptedGitRef


class PathDependency(_GemMetadata):
    """
    Represents a path dependency.

    Attributes:
        path:       Subpath from package root.
    """

    path: str


BundlerDependency = Union[GemDependency, GitDependency, PathDependency]
ParseResult = list[BundlerDependency]


def parse_lockfile(package_dir: RootedPath) -> ParseResult:
    """Parse a Gemfile.lock file and return a list of dependencies."""
    lockfile_path = package_dir.join_within_root(GEMFILE_LOCK)
    gemfile_path = package_dir.join_within_root(GEMFILE)
    if not lockfile_path.path.exists() or not gemfile_path.path.exists():
        reason = "Gemfile and Gemfile.lock must be present in the package directory"
        solution = (
            "Run `bundle init` to generate the Gemfile.\n"
            "Run `bundle lock` to generate the Gemfile.lock."
        )
        raise PackageRejected(reason=reason, solution=solution)

    scripts_dir = Path(__file__).parent / "scripts"
    lockfile_parser = scripts_dir / "lockfile_parser.rb"
    try:
        output = run_cmd(cmd=[str(lockfile_parser)], params={"cwd": package_dir.path})
    except subprocess.CalledProcessError:
        raise PackageManagerError(f"Failed to parse {lockfile_path}")

    json_output = json.loads(output)

    bundler_version: str = json_output["bundler_version"]
    log.info("Package %s is bundled with version %s", package_dir.path.name, bundler_version)
    dependencies: list[dict[str, str]] = json_output["dependencies"]

    result: ParseResult = []
    for dep in dependencies:
        if dep["type"] == "rubygems":
            result.append(GemDependency(**dep))
        elif dep["type"] == "git":
            result.append(GitDependency(**dep))
        elif dep["type"] == "path":
            _validate_path_dependency_subpath(package_dir, dep["path"])
            result.append(PathDependency(**dep))

    return result


def _validate_path_dependency_subpath(package_dir: RootedPath, path: str) -> None:
    """Validate that the path dependency is within the package root."""
    try:
        package_dir.join_within_root(path)
    except PathOutsideRoot:
        reason = "PATH dependencies should be within the package root"
        raise UnexpectedFormat(reason=reason)
