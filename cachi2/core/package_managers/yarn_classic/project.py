"""
Parse the relevant files of a yarn project.

It also provides basic utility functions. The main logic to resolve and prefetch
the dependencies should be implemented in other modules.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Literal, NamedTuple, Optional, Union

from pyarn import lockfile  # type: ignore

from cachi2.core.errors import PackageRejected
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(name=__name__)

ConfigKind = Literal["package_json", "yarnlock"]


@dataclass
class _CommonConfigFile(ABC):
    """A base class for representing a config file.

    :param path: the path to the config file, relative to the request source dir
    :param data: the raw data for the config file content
    """

    _path: RootedPath
    _data: dict[str, Any]

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    @property
    def path(self) -> RootedPath:
        return self._path

    @property
    @abstractmethod
    def config_kind(self) -> ConfigKind:
        """Return kind of ConfigFile instance."""
        pass

    @classmethod
    @abstractmethod
    def from_file(cls, path: RootedPath) -> "_CommonConfigFile":
        """Construct a ConfigFile instance."""
        pass


class PackageJson(_CommonConfigFile):
    """A package.json file.

    This class abstracts the underlying attributes and only exposes what
    is relevant for the request processing.
    """

    @property
    def config_kind(self) -> ConfigKind:
        """Return kind of this ConfigFile."""
        return "package_json"

    @property
    def package_manager(self) -> Optional[str]:
        """Get the package manager string."""
        return self.data.get("packageManager")

    @package_manager.setter
    def package_manager(self, package_manager: str) -> None:
        """Set the package manager string."""
        self.data["packageManager"] = package_manager

    @property
    def install_config(self) -> Optional[dict[str, Any]]:
        """Get the installConfig dict."""
        return self.data.get("installConfig", "")

    @classmethod
    def from_file(cls, path: RootedPath) -> "PackageJson":
        """Construct a PackageJson instance."""
        try:
            package_json_data = json.loads(path.path.read_text())
        except FileNotFoundError:
            raise PackageRejected(
                reason="The package.json file must be present for the yarn package manager",
                solution=(
                    "Please double-check that you have specified the correct path "
                    "to the package directory containing this file"
                ),
            )
        except json.decoder.JSONDecodeError as e:
            raise PackageRejected(
                reason=f"Can't parse the {path.subpath_from_root} file. {e}",
                solution=(
                    "The package.json file must contain valid JSON. "
                    "Refer to the parser error and fix the contents of the file."
                ),
            )

        return cls(path, package_json_data)


class YarnLock(_CommonConfigFile):
    """A yarn.lock file.

    This class abstracts the underlying attributes.
    """

    yarn_lockfile: lockfile.Lockfile

    @property
    def config_kind(self) -> ConfigKind:
        """Return kind of this ConfigFile."""
        return "yarnlock"

    @classmethod
    def from_file(cls, path: RootedPath) -> "YarnLock":
        """Parse the content of a yarn.lock file."""
        try:
            yarn_lockfile = lockfile.Lockfile.from_file(path)
        except FileNotFoundError:
            raise PackageRejected(
                reason="The yarn.lock file must be present for the yarn package manager",
                solution=(
                    "Please double-check that you have specified the correct path "
                    "to the package directory containing this file"
                ),
            )
        except ValueError as e:
            raise PackageRejected(
                reason=(f"Can't parse the {path.subpath_from_root} file.\n" f"{e}"),
                solution=(
                    "The yarn.lock file must be valid. "
                    "Refer to the parser error and fix the contents of the file."
                ),
            )

        if not yarn_lockfile:
            raise PackageRejected(
                reason="The yarn.lock file must not be empty",
                solution=("Please verify the content of the file."),
            )

        return cls(path, yarn_lockfile.data)


ConfigFile = Union[PackageJson, YarnLock]


class Project(NamedTuple):
    """A directory containing yarn sources."""

    source_dir: RootedPath
    package_json: PackageJson

    @property
    def is_pnp_install(self) -> bool:
        """Is the project is using Plug'n'Play (PnP) workflow or not.

        This is determined by
        - `installConfig.pnp: true` in 'package.json'
        - the existence of file(s) with glob name '*.pnp.cjs'
        - the presence of an expanded node_modules directory
        For more details on PnP, see: https://classic.yarnpkg.com/en/docs/pnp
        """
        is_pnp = False
        if (
            self.package_json.data.get("installConfig", {}).get("pnp", False) is True
            or any(PurePath(file).match("*.pnp.cjs") for file in self.source_dir.path.iterdir())
            or self.source_dir.join_within_root("node_modules").path.exists()
        ):
            is_pnp = True
        return is_pnp

    @classmethod
    def from_source_dir(cls, source_dir: RootedPath) -> "Project":
        """Create a Project from a sources directory path."""
        package_json = PackageJson.from_file(source_dir.join_within_root("package.json"))
        return cls(source_dir, package_json)
