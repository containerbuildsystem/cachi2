import re
from itertools import chain
from pathlib import Path
from typing import Iterable, Optional, Union
from urllib.parse import urlparse

from pyarn.lockfile import Package as PYarnPackage
from pydantic import BaseModel

from cachi2.core.errors import PackageRejected, UnexpectedFormat
from cachi2.core.package_managers.npm import NPM_REGISTRY_CNAMES
from cachi2.core.package_managers.yarn_classic.project import PackageJson, Project, YarnLock
from cachi2.core.rooted_path import RootedPath

# https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/resolvers/exotics/git-resolver.js#L15-L17
GIT_HOSTS = frozenset(("github.com", "gitlab.com", "bitbucket.com", "bitbucket.org"))
GIT_PATTERN_MATCHERS = (
    re.compile(r"^git:"),
    re.compile(r"^git\+.+:"),
    re.compile(r"^ssh:"),
    re.compile(r"^https?:.+\.git$"),
    re.compile(r"^https?:.+\.git#.+"),
)


class _BasePackage(BaseModel):
    """A base Yarn 1.x package."""

    name: str
    version: Optional[str] = None
    integrity: Optional[str] = None
    dev: bool = False


class _UrlMixin(BaseModel):
    url: str


class _RelpathMixin(BaseModel):
    relpath: Path


class RegistryPackage(_BasePackage, _UrlMixin):
    """A Yarn 1.x package from the registry."""


class GitPackage(_BasePackage, _UrlMixin):
    """A Yarn 1.x package from a git repo."""


class UrlPackage(_BasePackage, _UrlMixin):
    """A Yarn 1.x package from a http/https URL."""


class FilePackage(_BasePackage, _RelpathMixin):
    """A Yarn 1.x package from a local file path."""


class WorkspacePackage(_BasePackage, _RelpathMixin):
    """A Yarn 1.x local workspace package."""


class LinkPackage(_BasePackage, _RelpathMixin):
    """A Yarn 1.x local link package."""


YarnClassicPackage = Union[
    FilePackage,
    GitPackage,
    LinkPackage,
    RegistryPackage,
    UrlPackage,
    WorkspacePackage,
]


class _YarnClassicPackageFactory:
    def __init__(self, source_dir: RootedPath):
        self._source_dir = source_dir

    def create_package_from_pyarn_package(self, package: PYarnPackage) -> YarnClassicPackage:
        def assert_package_has_relative_path(package: PYarnPackage) -> None:
            if package.path and Path(package.path).is_absolute():
                raise PackageRejected(
                    (
                        f"The package {package.name}@{package.version} has an absolute path "
                        f"({package.path}), which is not permitted."
                    ),
                    solution="Ensure that file/link packages in yarn.lock do not have absolute paths.",
                )

        if _is_from_npm_registry(package.url):
            return RegistryPackage(
                name=package.name,
                version=package.version,
                integrity=package.checksum,
                url=package.url,
            )
        elif package.path is not None:
            # Ensure path is not absolute
            assert_package_has_relative_path(package)
            # Ensure path is within the repository root
            path = self._source_dir.join_within_root(package.path)
            # File packages have a url, whereas link packages do not
            if package.url:
                return FilePackage(
                    name=package.name,
                    version=package.version,
                    relpath=path.subpath_from_root,
                    integrity=package.checksum,
                )
            return LinkPackage(
                name=package.name,
                version=package.version,
                relpath=path.subpath_from_root,
            )
        elif _is_git_url(package.url):
            return GitPackage(
                name=package.name,
                version=package.version,
                url=package.url,
            )
        elif _is_tarball_url(package.url):
            return UrlPackage(
                name=package.name,
                version=package.version,
                url=package.url,
                integrity=package.checksum,
            )
        else:
            raise UnexpectedFormat(
                (
                    "Cachi2 could not determine the package type for the following package in "
                    f"yarn.lock: {vars(package)}"
                ),
                solution=(
                    "Ensure yarn.lock is well-formed and if so, report this error to the Cachi2 team"
                ),
            )


def _is_tarball_url(url: str) -> bool:
    """Return True if a package URL is a tarball URL."""
    # Parse the URL to extract components
    parsed_url = urlparse(url)

    # https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/resolvers/exotics/tarball-resolver.js#L34
    if parsed_url.scheme not in {"http", "https"}:
        return False

    # https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/resolvers/exotics/tarball-resolver.js#L40
    # https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/resolvers/exotics/bitbucket-resolver.js#L11
    # https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/resolvers/exotics/gitlab-resolver.js#L10C10-L10C23
    if parsed_url.path.endswith((".tar", ".tar.gz", ".tgz")):
        return True

    # https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/resolvers/exotics/github-resolver.js#L24
    if parsed_url.hostname == "codeload.github.com" and "tar.gz" in parsed_url.path:
        return True

    return False


def _is_git_url(url: str) -> bool:
    """Return True if a package URL is a git URL."""
    # https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/resolvers/exotics/git-resolver.js#L32
    if any(matcher.match(url) for matcher in GIT_PATTERN_MATCHERS):
        return True

    # https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/resolvers/exotics/git-resolver.js#L39
    parsed_url = urlparse(url)
    if parsed_url.hostname in GIT_HOSTS:
        path_segments = [segment for segment in parsed_url.path.split("/") if segment]
        # Return True if the path has exactly two segments (e.g. org/repo, not org/repo/file.tar.gz)
        return len(path_segments) == 2

    return False


def _is_from_npm_registry(url: str) -> bool:
    """Return True if a package URL is from the NPM or Yarn registry."""
    return urlparse(url).hostname in NPM_REGISTRY_CNAMES


def _get_packages_from_lockfile(
    source_dir: RootedPath, yarn_lock: YarnLock
) -> list[YarnClassicPackage]:
    """Return a list of Packages for all dependencies in yarn.lock."""
    pyarn_packages: list[PYarnPackage] = yarn_lock.yarn_lockfile.packages()
    package_factory = _YarnClassicPackageFactory(source_dir)

    return [
        package_factory.create_package_from_pyarn_package(package) for package in pyarn_packages
    ]


def _get_main_package(package_json: PackageJson) -> WorkspacePackage:
    """Return a WorkspacePackage for the main package in package.json."""
    if "name" not in package_json._data:
        raise PackageRejected(
            f"The package.json file located at {package_json.path.path} is missing the name field",
            solution="Ensure the package.json file has a valid name.",
        )
    return WorkspacePackage(
        name=package_json.data["name"],
        version=package_json.data.get("version"),
        relpath=package_json.path.subpath_from_root.parent,
    )


def resolve_packages(project: Project) -> Iterable[YarnClassicPackage]:
    """Return a list of Packages corresponding to all project dependencies."""
    yarn_lock = YarnLock.from_file(project.source_dir.join_within_root("yarn.lock"))
    return chain(
        [_get_main_package(project.package_json)],
        _get_packages_from_lockfile(project.source_dir, yarn_lock),
    )
