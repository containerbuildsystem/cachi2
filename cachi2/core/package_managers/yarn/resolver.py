"""
Resolve the dependency list for a yarn project.

It also performs the necessary validations to avoid allowing an invalid project to keep being
processed.
"""
import logging
from dataclasses import dataclass
from functools import cached_property

import pydantic
from packageurl import PackageURL

from cachi2.core.errors import UnsupportedFeature
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.yarn.locators import Locator, parse_locator
from cachi2.core.package_managers.yarn.project import Optional, Project
from cachi2.core.package_managers.yarn.utils import run_yarn_cmd
from cachi2.core.rooted_path import RootedPath

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


def create_components(packages: list[Package], project: Project) -> list[Component]:
    """Create SBOM components for all the packages parsed from the 'yarn info' output."""
    components = []
    for package in packages:
        name = _resolve_package_name(package)
        component = Component(
            name=name,
            version=package.version,
            purl=_generate_purl_for_package(package, name, project),
        )
        components.append(component)
    return components


def _resolve_package_name(package: Package) -> str:
    """Resolve the package's real name based on its protocol.

    Non-registry deps might have names in their locator string that differ from the one in their
    package.json file.

    Look at the package.json name for every non-registry dependency.
    """
    return "placeholder"


def _generate_purl_for_package(package: Package, name: str, project: Project) -> str:
    """Create a purl for a package based on its protocol.

    :param package: the package to be used in the purl generation.
    :param name: the real name of the package, resolved from its package.json file in case of
        non-registry dependencies.
    :param project: the project object to resolve the configured registry url and file paths
        for file dependencies.
    """
    # registry url can be accessed in project.yarnrc
    # paths for file dependencies are relative to project.source_dir
    return PackageURL(
        type="npm",
        name=name.lower(),
        version="placeholder",
        # TODO: used to make sure purls are unique even for an incomplete implementation
        #   remove raw_locator when no longer needed
        qualifiers={"raw_locator": package.raw_locator},
    ).to_string()
