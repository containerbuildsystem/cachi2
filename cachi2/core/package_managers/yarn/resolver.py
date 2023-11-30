"""
Resolve the dependency list for a yarn project.

It also performs the necessary validations to avoid allowing an invalid project to keep being
processed.
"""
import json
import logging
import zipfile
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Union

import pydantic
from packageurl import PackageURL

from cachi2.core.errors import PackageRejected, UnsupportedFeature
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.yarn.locators import (
    FileLocator,
    HttpsLocator,
    LinkLocator,
    Locator,
    NpmLocator,
    PatchLocator,
    PortalLocator,
    WorkspaceLocator,
    parse_locator,
)
from cachi2.core.package_managers.yarn.project import Optional, Project
from cachi2.core.package_managers.yarn.utils import run_yarn_cmd
from cachi2.core.rooted_path import RootedPath

if TYPE_CHECKING:
    # Import conditionally so that we don't have to introduce a runtime dependency on
    # typing-extensions. This is only imported when a type-checker is running.
    # In python 3.11, it can be imported directly from the stdlib 'typing' module.
    from typing_extensions import assert_never

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Package:
    """A package listed by the yarn info command.

    See the output for 'yarn info -AR --json --cache'.

    {
      "value": "{locator}"
      "children": {
        "Version": "{version}" or "0.0.0-use.local"
        "Cache": {
          "Checksum": "{cache_key}/{checksum}" or null
          "Path": "{cache_path}" or null
        }
      }
    }

    Note:
    - version will be None if yarn info reports 0.0.0-use.local (as it does for soft-link* deps).
    - checksum will be None for soft-link deps or deps that are missing the 'checksum' key in
      yarn.lock.
    - cache_path will be None for soft-link deps or, in some cases, deps that are missing the
      'checksum' key

    *soft-link = workspace, portal and link dependencies
    """

    raw_locator: str
    version: Optional[str]
    checksum: Optional[str]
    cache_path: Optional[str]

    @classmethod
    def from_info_string(cls, info: str) -> "Package":
        """Create a Package from the output of yarn info."""
        entry = _YarnInfoEntry.model_validate_json(info)
        locator = entry.value
        version: Optional[str] = entry.children.version
        if version == "0.0.0-use.local":
            version = None

        cache = entry.children.cache
        if cache.checksum:
            checksum = cache.checksum.split("/", 1)[-1]
        else:
            checksum = None

        return cls(locator, version, checksum, cache.path)

    @cached_property
    def parsed_locator(self) -> Locator:
        """Parse the raw_locator, store the parsed value for later re-use and return it."""
        return parse_locator(self.raw_locator)


class _YarnInfoCache(pydantic.BaseModel):
    checksum: Optional[str] = pydantic.Field(alias="Checksum")
    path: Optional[str] = pydantic.Field(alias="Path")


class _YarnInfoChildren(pydantic.BaseModel):
    version: str = pydantic.Field(alias="Version")
    cache: _YarnInfoCache = pydantic.Field(alias="Cache")


class _YarnInfoEntry(pydantic.BaseModel):
    value: str
    children: _YarnInfoChildren


def resolve_packages(source_dir: RootedPath) -> list[Package]:
    """Fetch and parse package data from the 'yarn info' output.

    This function also performs validation to ensure that the current yarn project can be
    processed.

    :raises UnsupportedFeature: if an unsupported locator type is found in 'yarn info' output
    :raises YarnCommandError: if the 'yarn info' command fails.
    """
    # --all: report dependencies of all workspaces, not just the active workspace
    # --recursive: report transitive dependencies, not just direct ones
    # --cache: include info about the cache entry for each dependency
    result = run_yarn_cmd(["info", "--all", "--recursive", "--cache", "--json"], source_dir)

    # the result is not a valid json list, but a sequence of json objects separated by line breaks
    packages = [Package.from_info_string(info) for info in result.splitlines()]

    n_unsupported = 0
    for package in packages:
        try:
            _ = package.parsed_locator
        except UnsupportedFeature as e:
            log.error(e)
            n_unsupported += 1

    if n_unsupported > 0:
        raise UnsupportedFeature(
            f"Found {n_unsupported} unsupported dependencies, more details in the logs."
        )

    return packages


def create_components(
    packages: list[Package], project: Project, output_dir: RootedPath
) -> list[Component]:
    """Create SBOM components for all the packages parsed from the 'yarn info' output."""
    package_mapping = {package.parsed_locator: package for package in packages}
    component_resolver = _ComponentResolver(package_mapping, project, output_dir)
    return [component_resolver.get_component(package) for package in package_mapping.values()]


@dataclass(frozen=True)
class _ResolvedPackage:
    """A resolved package.

    Compared to the Package class:
    - has a name attribute even if the locator doesn't include a reliable name
      (the name is resolved from the package.json of the package)
    - has a reliable version (resolved from package.json when necessary)
    """

    locator: Locator
    name: str
    version: Optional[str]

    # TODO: used to make sure purls are unique even for an incomplete implementation
    #   remove raw_locator when no longer needed
    raw_locator: str


class _CouldNotResolve(ValueError):
    """_ComponentResolver failed to resolve the name or version of a package."""


class _ComponentResolver:
    def __init__(
        self, package_mapping: Mapping[Locator, Package], project: Project, output_dir: RootedPath
    ) -> None:
        self._project = project
        self._output_dir = output_dir
        self._package_mapping = package_mapping

    def get_component(self, package: Package) -> Component:
        """Create an SBOM component for a yarn Package."""
        try:
            resolved_package = self._resolve_package(package)
        except _CouldNotResolve as e:
            raise PackageRejected(
                f"Failed to resolve the name and version for {package.raw_locator}: {e}",
                solution=(
                    "Please try running 'yarn install' to see if yarn makes any changes.\n"
                    "If yarn succeeds and doesn't make any changes, please report this Cachi2 bug."
                ),
            ) from e

        purl = self._generate_purl_for_package(resolved_package, self._project)

        return Component(
            name=resolved_package.name,
            version=resolved_package.version,
            purl=purl,
        )

    @staticmethod
    def _generate_purl_for_package(package: _ResolvedPackage, project: Project) -> str:
        """Create a purl for a package based on its protocol.

        :param package: the resolved package to be used in the purl generation.
        :param project: the project object to resolve the configured registry url and file paths
            for file dependencies.
        """
        # registry url can be accessed in project.yarnrc
        # paths for file dependencies are relative to project.source_dir
        return PackageURL(
            type="npm",
            name=package.name.lower(),
            version=package.version,
            # TODO: used to make sure purls are unique even for an incomplete implementation
            #   remove raw_locator when no longer needed
            qualifiers={"raw_locator": package.raw_locator},
        ).to_string()

    def _resolve_package(self, package: Package) -> _ResolvedPackage:
        """Resolve the real name and version of the package."""

        def log_for_locator(msg: str, *args: Any, level: int = logging.DEBUG) -> None:
            log.log(level, f"%s: {msg}", package.raw_locator, *args)

        locator = package.parsed_locator

        if isinstance(locator, NpmLocator):
            # npm dependencies have reliable names and versions in yarn info output
            name = self._scoped_name(locator)
            version = package.version
        elif isinstance(locator, WorkspaceLocator):
            packjson = self._project_subpath(locator.relpath, "package.json")
            log_for_locator("reading package version from %s", packjson.subpath_from_root)
            # workspace dependencies have reliable names but report '0.0.0-use.local' as the version
            name = self._scoped_name(locator)
            _, version = self._read_name_version_from_packjson(packjson)
        elif isinstance(locator, (FileLocator, HttpsLocator)):
            if not package.cache_path:
                raise _CouldNotResolve(
                    "expected a zip archive in the cache but 'yarn info' says there is none",
                )
            cache_path = self._cache_path_as_rooted(package.cache_path)
            if not cache_path.path.exists():
                raise _CouldNotResolve(
                    f"cache archive does not exist: {cache_path.subpath_from_root}"
                )
            log_for_locator("reading package name from %s", cache_path.subpath_from_root)
            # file and https dependencies have reliable versions but unreliable names
            name = self._read_name_from_cache(cache_path)
            version = package.version
        elif isinstance(locator, (PortalLocator, LinkLocator)):
            parent_locator = locator.locator
            packjson = self._project_subpath(
                parent_locator.relpath, locator.relpath, "package.json"
            )
            if isinstance(locator, LinkLocator) and not packjson.path.exists():
                # if a link dependency doesn't have a package.json, we have to rely on the locator
                name = self._scoped_name(locator)
                version = None
            else:
                # otherwise, take both the name and the version from package.json
                # (name is unreliable, version is '0.0.0-use.local')
                log_for_locator(
                    "reading package name and version from %s", packjson.subpath_from_root
                )
                name, version = self._read_name_version_from_packjson(packjson)
        elif isinstance(locator, PatchLocator):
            if (
                package.cache_path
                # yarn info seems to always report the cache path for patch dependencies,
                # but the path doesn't always exist
                and (cache_path := self._cache_path_as_rooted(package.cache_path)).path.exists()
            ):
                log_for_locator("reading package name from %s", cache_path.subpath_from_root)
                name = self._read_name_from_cache(cache_path)
            elif orig_package := self._package_mapping.get(locator.package):
                log_for_locator("resolving the name of the original package")
                name = self._resolve_package(orig_package).name
            else:
                raise _CouldNotResolve(
                    "the 'yarn info' output does not include either an existing zip archive "
                    "or the original unpatched package",
                )
            version = package.version
        else:
            # This line can never be reached assuming type-checker checks are passing
            # https://typing.readthedocs.io/en/latest/source/unreachable.html#assert-never-and-exhaustiveness-checking
            assert_never(locator)

        return _ResolvedPackage(locator, name, version, package.raw_locator)

    def _read_name_from_cache(self, cache_path: RootedPath) -> str:
        with zipfile.ZipFile(cache_path) as zf:
            packjson_paths = (
                filename
                for filename in zf.namelist()
                # node_modules/@scope/name/package.json
                # node_modules/name/package.json
                if (path := Path(filename)).parts[0] == "node_modules"
                and len(path.parts) in (3, 4)
                and path.parts[-1] == "package.json"
            )
            packjson_path = next(packjson_paths, None)
            if packjson_path is None:
                raise _CouldNotResolve(f"{cache_path.subpath_from_root}: no package.json")

            packjson_content = zf.read(packjson_path)

        try:
            packjson = json.loads(packjson_content)
        except json.JSONDecodeError as e:
            raise _CouldNotResolve(
                f"{cache_path.subpath_from_root}::{packjson_path}: invalid JSON ({e})"
            ) from e

        if not (name := packjson.get("name")):
            raise _CouldNotResolve(
                f"{cache_path.subpath_from_root}::{packjson_path}: no 'name' attribute"
            )

        return name

    def _scoped_name(self, locator: Union[NpmLocator, WorkspaceLocator, LinkLocator]) -> str:
        if locator.scope:
            return f"@{locator.scope}/{locator.name}"
        return locator.name

    def _read_name_version_from_packjson(
        self, packjson_path: RootedPath
    ) -> tuple[str, Optional[str]]:
        try:
            packjson = json.loads(packjson_path.path.read_text())
        except FileNotFoundError as e:
            raise _CouldNotResolve(f"missing {packjson_path.subpath_from_root}") from e
        except json.JSONDecodeError as e:
            raise _CouldNotResolve(f"{packjson_path.subpath_from_root}: invalid JSON ({e})") from e

        if not (name := packjson.get("name")):
            raise _CouldNotResolve(f"{packjson_path.subpath_from_root}: no 'name' attribute")

        return name, packjson.get("version")

    def _project_subpath(self, *parts: Union[str, Path]) -> RootedPath:
        return self._project.source_dir.join_within_root(*parts)

    def _cache_path_as_rooted(self, cache_path: str) -> RootedPath:
        if Path(cache_path).is_relative_to(self._project.source_dir):
            return self._project_subpath(cache_path)
        else:
            return self._output_dir.join_within_root(cache_path)
