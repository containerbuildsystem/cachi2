import json
import logging
import subprocess
from functools import cached_property
from pathlib import Path
from typing import Annotated, Optional, Union
from urllib.parse import urlparse

import pydantic
from git import Repo
from typing_extensions import Self

from cachi2.core.errors import PackageManagerError, PackageRejected
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

    def download_to(self, deps_dir: RootedPath) -> None:
        """Download gem to the specified directory."""
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

    def download_to(self, deps_dir: RootedPath) -> None:
        """Download represented gem to specified file system location."""
        fs_location = deps_dir.join_within_root(Path(f"{self.name}-{self.version}.gem"))
        log.info("Downloading gem %s", self.name)
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

    @cached_property
    def repo_name(self) -> str:
        """Extract the repository name from the URL."""
        parse_result = urlparse(str(self.url))
        return Path(parse_result.path).stem

    def download_to(self, deps_dir: RootedPath) -> None:
        """Download git repository to the output directory with a specific name."""
        short_ref_length = 12
        short_ref = self.ref[:short_ref_length]

        git_repo_path = deps_dir.join_within_root(f"{self.repo_name}-{short_ref}")
        if git_repo_path.path.exists():
            log.info("Skipping existing git repository %s", self.url)
            return

        git_repo_path.path.mkdir(parents=True)

        log.info("Cloning git repository %s", self.url)
        repo = Repo.clone_from(
            url=str(self.url),
            to_path=git_repo_path.path,
            env={"GIT_TERMINAL_PROMPT": "0"},
        )
        repo.git.checkout(self.ref)


class PathDependency(_GemMetadata):
    """
    Represents a path dependency.

    Attributes:
        root:       The root of the package.
        subpath:    Subpath from the package root.
    """

    root: RootedPath
    subpath: str

    @pydantic.model_validator(mode="after")
    def validate_subpath(self) -> Self:
        """Validate that the subpath is within the package root."""
        try:
            self.root.join_within_root(self.subpath)
        except PathOutsideRoot:
            raise ValueError("PATH dependencies should be within the package root")

        return self


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
            result.append(PathDependency(**dep, root=package_dir))

    return result
