"""
Parse the relevant files of a yarn project.

It also provides basic utility functions. The main logic to resolve and prefetch
the dependencies should be implemented in other modules.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, Optional, Union

import yaml
from pyarn import lockfile

from cachi2.core.errors import PackageRejected
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(name=__name__)


DEFAULT_CACHE_FOLDER = "./.yarn/cache"


@dataclass
class _CommonConfigFile:
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
    def config_type(self) -> Literal["package_json", "yarnrc", "yarnlock"]:
        if isinstance(self, PackageJson):
            return "package_json"
        elif isinstance(self, YarnRc):
            return "yarnrc"
        elif isinstance(self, YarnLock):
            return "yarnlock"
        else:
            raise  # TODO: something

    @classmethod
    def from_file(cls, path: RootedPath) -> "_CommonConfigFile":
        """Parse the content of a config file."""
        return cls(path, {})

    def write(self) -> None:
        """Write the data to the config file."""
        with self.path.path.open("w") as f:
            repr(self.data)
            f.write("\n")


class PackageJson(_CommonConfigFile):
    """A package.json file.

    This class abstracts the underlying attributes and only exposes what
    is relevant for the request processing.
    """

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
        """Parse the content of a package.json file."""
        try:
            with path.path.open("r") as f:
                package_json_data = json.load(f)
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


class YarnRc(_CommonConfigFile):
    """A yarnrc file."""

    _cache_folder: Optional[str]

    @property
    def cache_folder(self) -> str:
        """Get the configured location for the yarn cache folder.

        Fallback to the default path in case the configuration key is missing.
        """
        return self._data.get("--cache-folder", DEFAULT_CACHE_FOLDER)

    @classmethod
    def from_file(cls, path: RootedPath) -> "YarnRc":
        """Parse the content of a yarnrc file.

        .yarnrc file are seriously dumb, just plain text keys and values with a
        single space in between. According to
        https://classic.yarnpkg.com/en/docs/yarnrc, paths should be quoted

        `yarn-offline-mirror "./packages-cache"`

        CLI syntax is possible

        `--install.check-files true`

        but paths don't have to be quoted(?!)

        `--cache-folder /tmp/yarn-cache/`
        """

        yarnrc_data = {}
        try:
            with path.path.open("r") as f:
                for line in f:
                    line = line.replace("\n", "").strip()
                    if line:
                        key_and_val = line.split(" ", 1)
                        yarnrc_data[key_and_val[0]] = key_and_val[1]
        except ValueError as e:
            raise PackageRejected(
                reason=f"Can't parse the {path.subpath_from_root} file. Parser error: {e}",
                solution=(
                    "The yarnrc file must contain valid data."
                    "Refer to the parser error and fix the contents of the file."
                ),
            )

        if not yarnrc_data:
            # warn
            pass

        return cls(path, yarnrc_data)

    @classmethod
    def from_str(cls, string: str) -> dict[str, Any]:
        """Parse the content of a string containing the contents of a valid yarnrc file."""
        yarnrc_data = {}
        try:
            for line in string.splitlines():
                line.strip()
                if line:
                    key_and_val = line.split(" ", 1)
                    yarnrc_data[key_and_val[0]] = key_and_val[1]
        except ValueError as e:
            raise PackageRejected(
                reason=f"Can't parse the string. Parser error: {e}",
                solution=(
                    "The string must contain valid yarnrc data."
                    "Refer to the parser error and fix the contents of the string."
                ),
            )

        if not yarnrc_data:
            # warn
            pass

        return yarnrc_data

    def write(self) -> None:
        """Write the data to the yarnrc file."""
        with self._path.path.open("w") as f:
            yaml.safe_dump(self._data, f)


class YarnLock(_CommonConfigFile):
    """A yarn.lock file.

    This class abstracts the underlying attributes.
    """

    yarn_lockfile: lockfile.Lockfile

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

    def write(self) -> None:
        """Write the data to the yarn.lock file."""
        self.yarn_lockfile.to_file(self.path)


ConfigFile = Union[PackageJson, YarnRc, YarnLock]


class Project(NamedTuple):
    """A directory containing yarn sources."""

    source_dir: RootedPath
    yarn_rc: YarnRc
    package_json: PackageJson

    @property
    def is_pnp_install(self) -> bool:
        """Is the project is using Plug'n'Play (PnP) workflow or not.

        This is determined by
        - `installConfig.pnp: true` in 'package.json'
        - the existence of file(s) with glob name '*.pnp.cjs'
        - the existence of a yarn cache folder containing zip files(default PnP mode)
        - the presence of an expanded node_modules directory
        For more details on PnP, see: https://classic.yarnpkg.com/en/docs/pnp
        """
        # if installConfig.pnp:
        #     if self.yarn_cache.path.exists() and self.yarn_cache.path.is_dir():
        #         # in this case the cache folder will be populated with downloaded ZIP dependencies
        #         return any(file.suffix == ".zip" for file in self.yarn_cache.path.iterdir())

        return False

    @property
    def yarn_cache(self) -> RootedPath:
        """The path to the yarn cache folder.

        The cache location is affected by the CLI parms, yarnrc, and env vars.
        See: https://classic.yarnpkg.com/en/docs/cli/cache.
        Doc for converting CLI parms to rc syntax:
        https://classic.yarnpkg.com/en/docs/yarnrc#toc-cli-arguments
        """
        return self.source_dir.join_within_root(self.yarn_rc.cache_folder)

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
