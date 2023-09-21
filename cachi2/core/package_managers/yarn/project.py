"""
Parse the relevant files of a yarn project.

It also provides basic utility functions. The main logic to resolve and prefetch the dependencies
should be implemented in other modules.
"""
from typing import Any, NamedTuple, Optional

from cachi2.core.rooted_path import RootedPath


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

    @classmethod
    def from_file(cls, file_path: RootedPath) -> "PackageJson":
        """Parse the content of a package.json file."""
        return NotImplemented


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
        return NotImplemented

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
        return NotImplemented
