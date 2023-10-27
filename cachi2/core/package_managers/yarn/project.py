"""
Parse the relevant files of a yarn project.

It also provides basic utility functions. The main logic to resolve and prefetch the dependencies
should be implemented in other modules.
"""
import json
import logging
import re
from collections import UserDict
from pathlib import Path
from typing import Any, NamedTuple, Optional

import semver
import yaml

from cachi2.core.errors import PackageRejected, UnexpectedFormat
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


DEFAULT_CACHE_FOLDER = "./.yarn/cache"
DEFAULT_REGISTRY = "https://registry.yarnpkg.com"


class YarnRc(UserDict):
    """A yarnrc file.

    This class abstracts the underlying attributes of a .yarnrc YAML
    configuration file.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialize a YarnRc dictionary.

        :param data: the raw data for the yarnrc file.
        """
        super().__init__(data)
        self._data = data

    @property
    def cache_folder(self) -> str:
        """Get the configured location for the yarn cache folder.

        Fallback to the default path in case the configuration key is missing.
        """
        return self._data.get("cacheFolder", DEFAULT_CACHE_FOLDER)

    @property
    def registry_server(self) -> str:
        """Get the globally configured registry server.

        Fallback to the default server in case the configuration key is missing.
        """
        return self._data.get("npmRegistryServer", DEFAULT_REGISTRY)

    @property
    def yarn_path(self) -> Optional[str]:
        """Path to the yarn script present in this directory."""
        return self._data.get("yarnPath")

    def registry_server_for_scope(self, scope: str) -> str:
        """Get the configured registry server for a scoped package.

        Fallback to the global defined registry server if there's no configuration for this specific
        scope.

        See: https://v3.yarnpkg.com/configuration/yarnrc#npmScopes
        """
        registry = self._data.get("npmScopes", {}).get(scope, {}).get("npmRegistryServer")

        return registry or self.registry_server

    @classmethod
    def from_file(cls, file_path: RootedPath) -> "YarnRc":
        """Parse the content of a yarnrc file.

        :param path: the path to the yarnrc file, relative to the request source dir.
        """
        try:
            with file_path.path.open("r") as f:
                yarnrc_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise PackageRejected(
                f"Can't parse the {file_path.subpath_from_root} file. Parser error: {e}",
                solution=(
                    "The yarnrc file must contain valid YAML. "
                    "Refer to the parser error and fix the contents of the file."
                ),
            )

        if yarnrc_data is None:
            yarnrc_data = {}

        return cls(yarnrc_data)


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
        return self._data.get("packageManager")

    @package_manager.setter
    def package_manager(self, package_manager: str) -> None:
        """Set the package manager string."""
        self._data["packageManager"] = package_manager

    @classmethod
    def from_file(cls, file_path: RootedPath) -> "PackageJson":
        """Parse the content of a package.json file."""
        try:
            with file_path.path.open("r") as f:
                package_json_data = json.load(f)
        except FileNotFoundError:
            raise PackageRejected(
                "The package.json file must be present for the yarn package manager",
                solution=(
                    "Please double-check that you have specified the correct path "
                    "to the package directory containing this file"
                ),
            )
        except json.decoder.JSONDecodeError as e:
            raise PackageRejected(
                f"Can't parse the {file_path.subpath_from_root} file. {e}",
                solution=(
                    "The package.json file must contain valid JSON. "
                    "Refer to the parser error and fix the contents of the file."
                ),
            )

        return cls(file_path, package_json_data)

    def write_to_file(self) -> None:
        """Write the data to the package.json file."""
        with self._path.path.open("w") as f:
            json.dump(self._data, f, indent=2)
            f.write("\n")


class Project(NamedTuple):
    """A directory containing yarn sources."""

    source_dir: RootedPath
    yarn_rc: Optional[YarnRc]
    package_json: PackageJson

    @property
    def is_zero_installs(self) -> bool:
        """If a project is using the zero-installs workflow or not.

        This is determined by the existence of a non-empty yarn cache folder. For more details on
        zero-installs, see: https://v3.yarnpkg.com/features/zero-installs.
        """
        dir = self.yarn_cache

        if not dir.path.is_dir():
            return False

        return any(file.suffix == ".zip" for file in dir.path.iterdir())

    @property
    def yarn_cache(self) -> RootedPath:
        """The path to the yarn cache folder.

        The cache location is affected by the cacheFolder configuration in yarnrc. See:
        https://v3.yarnpkg.com/configuration/yarnrc#cacheFolder.
        """
        if self.yarn_rc:
            return self.source_dir.join_within_root(self.yarn_rc.cache_folder)

        return self.source_dir.join_within_root(DEFAULT_CACHE_FOLDER)

    @classmethod
    def from_source_dir(cls, source_dir: RootedPath) -> "Project":
        """Create a Project from a sources directory path."""
        yarn_rc_path = source_dir.join_within_root(".yarnrc.yml")

        if yarn_rc_path.path.exists():
            yarn_rc = YarnRc.from_file(source_dir.join_within_root(".yarnrc.yml"))
        else:
            yarn_rc = None

        package_json = PackageJson.from_file(source_dir.join_within_root("package.json"))
        return cls(source_dir, yarn_rc, package_json)


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
