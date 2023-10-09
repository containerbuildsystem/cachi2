"""
Parse the relevant files of a yarn project.

It also provides basic utility functions. The main logic to resolve and prefetch the dependencies
should be implemented in other modules.
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, NamedTuple, Optional

import semver

from cachi2.core.errors import UnexpectedFormat
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


class YarnRc:
    """A yarnrc file.

    This class abstracts the underlying attributes and only exposes what
    is relevant for the request processing.
    """

    def __init__(self, path: RootedPath, data: dict[str, Any]) -> None:
        """Initialize a YarnRc object.

        :param path: the path to the yarnrc file, relative to the request source dir.
        :param data: the raw data for the yarnrc file.
        """
        self._path = path
        self._data = data

    @property
    def cache_path(self) -> str:
        """Get the configured location for the yarn cache folder.

        Fallback to the default path in case the configuration key is missing.
        """
        return NotImplemented

    @property
    def registry_server(self) -> str:
        """Get the globally configured registry server.

        Fallback to the default server in case the configuration key is missing.
        """
        return NotImplemented

    @property
    def yarn_path(self) -> Optional[str]:
        """Path to the yarn script present in this directory."""
        return NotImplemented

    @property
    def yarn_version(self) -> Optional[str]:
        """Yarn version used in this project.

        Extracted from the contents of the yarnPath configuration, if it is present.
        """
        return NotImplemented

    def registry_server_for_scope(self, scope: str) -> str:
        """Get the configured registry server for a scoped package.

        Fallback to the global defined registry server if there's no configuration for this specific
        scope.

        See: https://v3.yarnpkg.com/configuration/yarnrc#npmScopes
        """
        return NotImplemented

    @classmethod
    def from_file(cls, file_path: RootedPath) -> "YarnRc":
        """Parse the content of a yarnrc file."""
        return NotImplemented


class PackageJson:
    """A package.json file.

    This class abstracts the underlying attributes and only exposes what
    is relevant for the request processing.
    """

    def __init__(self, path: RootedPath, data: dict[str, Any]) -> None:
        """Initialize a PackageJson object.

        :param path: the path to the package.json file.
        :param data: the raw data for the package.json file.
        """
        self._path = path
        self._data = data

    @property
    def package_manager(self) -> Optional[str]:
        """Get the package manager string."""
        return NotImplemented

    @package_manager.setter
    def package_manager(self, package_manager: str) -> None:
        """Set the package manager string."""
        self._data["packageManager"] = package_manager

    @classmethod
    def from_file(cls, file_path: RootedPath) -> "PackageJson":
        """Parse the content of a package.json file."""
        return NotImplemented

    def write_to_file(self) -> None:
        """Write the data to the package.json file."""
        with self._path.path.open("w") as f:
            json.dump(self._data, f, indent=2)
            f.write("\n")


class Project(NamedTuple):
    """A directory containing yarn sources."""

    source_dir: RootedPath
    yarn_rc: YarnRc
    package_json: PackageJson

    @property
    def is_zero_installs(self) -> bool:
        """If a project is using the zero-installs workflow or not.

        This is determined by the existence of a non-empty yarn cache folder. For more details on
        zero-installs, see: https://v3.yarnpkg.com/features/zero-installs.
        """
        return False

    @property
    def yarn_cache(self) -> RootedPath:
        """The path to the yarn cache folder.

        The cache location is affected by the cacheFolder configuration in yarnrc. See:
        https://v3.yarnpkg.com/configuration/yarnrc#cacheFolder.
        """
        return NotImplemented

    @classmethod
    def from_source_dir(cls, source_dir: RootedPath) -> "Project":
        """Create a Project from a sources directory path."""
        return cls(source_dir, NotImplemented, NotImplemented)


def get_semver_from_yarn_path(yarn_path: Optional[str]) -> Optional[semver.version.Version]:
    """Parse yarnPath from yarnrc and return a semver Version if possible else None."""
    if not yarn_path:
        return None

    # https://github.com/yarnpkg/berry/blob/2dc59443e541098bc0104d97b5fc452781c64baf/packages/plugin-essentials/sources/commands/set/version.ts#L208
    yarn_spec_pattern = re.compile(r"^yarn-(.+)\.cjs$")
    match = yarn_spec_pattern.match(Path(yarn_path).name)
    if not match:
        log.warning(
            (
                "The yarn version specified by yarnPath in .yarnrc.yml (%s) does not match the "
                "expected format yarn-<semver>.cjs. Attempting to use the version specified by "
                "packageManager in package.json."
            ),
            yarn_path,
        )
        return None

    yarn_version = match.group(1)
    try:
        return semver.version.Version.parse(yarn_version)
    except ValueError:
        log.warning(
            (
                "The yarn version specified by yarnPath in .yarnrc.yml (%s) is not a valid semver. "
                "Attempting to use the version specified by packageManager in package.json."
            ),
            yarn_path,
        )
        return None


def get_semver_from_package_manager(
    package_manager: Optional[str],
) -> Optional[semver.version.Version]:
    """Parse packageManager from package.json and return a semver Version if possible.

    :raises UnexpectedFormat:
        if packageManager doesn't match the name@semver format
        if packageManager does not specify yarn
        if packageManager version is not a valid semver
    """
    if not package_manager:
        return None

    # https://github.com/nodejs/corepack/blob/787e24df609513702eafcd8c6a5f03544d7d45cc/sources/specUtils.ts#L10
    package_manager_spec_pattern = re.compile(r"^(?!_)(.+)@(.+)$")
    match = package_manager_spec_pattern.match(package_manager)
    if not match:
        raise UnexpectedFormat(
            "could not parse packageManager spec in package.json (expected name@semver)"
        )

    name, version = match.groups()
    if name != "yarn":
        raise UnexpectedFormat("packageManager in package.json must be yarn")

    try:
        return semver.version.Version.parse(version)
    except ValueError as e:
        raise UnexpectedFormat(
            f"{version} is not a valid semver for packageManager in package.json"
        ) from e
