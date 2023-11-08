"""
Parse the relevant files of a yarn project.

It also provides basic utility functions. The main logic to resolve and prefetch the dependencies
should be implemented in other modules.
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, Literal, NamedTuple, Optional, TypedDict

import semver
import yaml

from cachi2.core.errors import PackageRejected, UnexpectedFormat
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


DEFAULT_CACHE_FOLDER = "./.yarn/cache"
DEFAULT_REGISTRY = "https://registry.yarnpkg.com"

ChecksumBehavior = Literal["throw", "update", "ignore"]
PnpMode = Literal["strict", "loose"]
NodeLinker = Literal["pnp", "pnpm", "node-modules"]


class Plugin(TypedDict):
    """A plugin defined in the yarnrc file."""

    path: str
    spec: str


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
    def cache_folder(self) -> str:
        """Get the configured location for the yarn cache folder.

        Fallback to the default path in case the configuration key is missing.
        """
        return self._data.get("cacheFolder", DEFAULT_CACHE_FOLDER)

    @property
    def checksum_behavior(self) -> Optional[ChecksumBehavior]:
        """Get the checksumBehavior configuration."""
        return self._data.get("checksumBehavior", None)

    @checksum_behavior.setter
    def checksum_behavior(self, checksum_behavior: Optional[ChecksumBehavior]) -> None:
        self._data["checksumBehavior"] = checksum_behavior

    @property
    def enable_immutable_cache(self) -> Optional[bool]:
        """Get the enableImmutableCache configuration."""
        return self._data.get("enableImmutableCache", None)

    @enable_immutable_cache.setter
    def enable_immutable_cache(self, enable_immutable_cache: Optional[bool]) -> None:
        self._data["enableImmutableCache"] = enable_immutable_cache

    @property
    def enable_immutable_installs(self) -> Optional[bool]:
        """Get the enableImmutableInstalls configuration."""
        return self._data.get("enableImmutableInstalls", None)

    @enable_immutable_installs.setter
    def enable_immutable_installs(self, enable_immutable_installs: Optional[bool]) -> None:
        self._data["enableImmutableInstalls"] = enable_immutable_installs

    @property
    def enable_mirror(self) -> Optional[bool]:
        """Get the enableMirror configuration."""
        return self._data.get("enableMirror", None)

    @enable_mirror.setter
    def enable_mirror(self, enable_mirror: Optional[bool]) -> None:
        self._data["enableMirror"] = enable_mirror

    @property
    def enable_scripts(self) -> Optional[bool]:
        """Get the enableScripts configuration."""
        return self._data.get("enableScripts", None)

    @enable_scripts.setter
    def enable_scripts(self, enable_scripts: Optional[bool]) -> None:
        self._data["enableScripts"] = enable_scripts

    @property
    def enable_strict_ssl(self) -> Optional[bool]:
        """Get the enableStrictSsl configuration."""
        return self._data.get("enableStrictSsl", None)

    @enable_strict_ssl.setter
    def enable_strict_ssl(self, enable_strict_ssl: Optional[bool]) -> None:
        self._data["enableStrictSsl"] = enable_strict_ssl

    @property
    def enable_telemetry(self) -> Optional[bool]:
        """Get the enableTelemetry configuration."""
        return self._data.get("enableTelemetry", None)

    @enable_telemetry.setter
    def enable_telemetry(self, enable_telemetry: Optional[bool]) -> None:
        self._data["enableTelemetry"] = enable_telemetry

    @property
    def global_folder(self) -> Optional[str]:
        """Get the global folder."""
        return self._data.get("globalFolder", None)

    @global_folder.setter
    def global_folder(self, global_folder: Optional[str]) -> None:
        self._data["globalFolder"] = global_folder

    @property
    def pnp_mode(self) -> Optional[PnpMode]:
        """Get the pnpMode configuration."""
        return self._data.get("pnpMode", None)

    @pnp_mode.setter
    def pnp_mode(self, mode: Optional[PnpMode]) -> None:
        self._data["pnpMode"] = mode

    @property
    def ignore_path(self) -> Optional[bool]:
        """Get the ignorePath configuration."""
        return self._data.get("ignorePath", None)

    @ignore_path.setter
    def ignore_path(self, ignore_path: Optional[bool]) -> None:
        self._data["ignorePath"] = ignore_path

    @property
    def unsafe_http_whitelist(self) -> list[str]:
        """Get the whitelisted urls that can be accessed via http.

        Returns an empty array in case there are none defined.
        """
        return self._data.get("unsafeHttpWhitelist", [])

    @unsafe_http_whitelist.setter
    def unsafe_http_whitelist(self, urls: list[str]) -> None:
        self._data["unsafeHttpWhitelist"] = urls

    @property
    def node_linker(self) -> NodeLinker:
        """Get the nodeLinker configuration."""
        return self._data.get("nodeLinker", None)

    @node_linker.setter
    def node_linker(self, node_linker: Optional[NodeLinker]) -> None:
        self._data["nodeLinker"] = node_linker

    @property
    def plugins(self) -> list[Plugin]:
        """Get the configured plugins.

        Returns an empty array in case there are none defined.
        """
        return self._data.get("plugins", [])

    @plugins.setter
    def plugins(self, plugins: list[Plugin]) -> None:
        self._data["plugins"] = plugins

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

    def write(self) -> None:
        """Write the data to the yarnrc file."""
        with self._path.path.open("w") as f:
            yaml.safe_dump(self._data, f)

    @classmethod
    def from_file(cls, file_path: RootedPath) -> "YarnRc":
        """Parse the content of a yarnrc file."""
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

        return cls(file_path, yarnrc_data)


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

    def write(self) -> None:
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
            yarn_rc = YarnRc.from_file(yarn_rc_path)
        else:
            yarn_rc = YarnRc(yarn_rc_path, {})

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
