"""
Resolve the dependency list for a yarn project.

It also performs the necessary validations to avoid allowing an invalid project to keep being
processed.
"""
import logging
from typing import NamedTuple

from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.yarn.locators import Locator
from cachi2.core.package_managers.yarn.project import Optional, Project
from cachi2.core.package_managers.yarn.utils import run_yarn_cmd
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


class Cache(NamedTuple):
    """Cache information for a package."""

    checksum: str
    path: str


class Package(NamedTuple):
    """A package listed by the yarn info command.

    See the output for 'yarn info -AR --json --cache'.

    Note that the attributes present in the json vary a little depending on the type of
    dependency.
    """

    # cache seems to be optional for portal, link and workspace protocols.
    # 'yarn info' returns a cache object with empty keys.
    cache: Optional[Cache]
    locator: Locator
    version: str

    @classmethod
    def from_info_string(cls, info: str) -> "Package":
        """Create a Package from the output of yarn info."""
        # this should use the locators.parse_locator function
        return NotImplemented


def resolve_packages(source_dir: RootedPath) -> list[Package]:
    """Fetch and parse package data from the 'yarn info' output.

    This function also performs a validation to ensure that the current yarn project can be
    processed.

    :raises PackageRejected: if the validation fails.
    :raises SubprocessCallError: if the 'yarn info' command fails.
    """
    under_development = True
    if under_development:
        return []

    result = run_yarn_cmd([], source_dir, {})

    # the result is not a valid json list, but a sequence of json objects separated by line breaks
    packages = [Package.from_info_string(info) for info in result.splitlines()]

    _vet_git_dependencies(packages)

    return packages


def create_component_from_package(package: Package, project: Project) -> Component:
    """Create a SBOM component from a yarn Package."""
    # if the SBOM generation code grows too much, it may be a good idea to split it into a dedicated
    # module.

    name = _resolve_package_name(package)

    return Component(
        name=name, version=package.version, purl=_generate_purl_for_package(package, name, project)
    )


def _vet_git_dependencies(packages: list[Package]) -> None:
    """Stop the request processing if a Git dependency is found.

    Git dependencies will cause the execution of existing js lifecycle scripts when 'yarn install'
    is called, which results in arbitrary code execution in Cachi2.

    :raises PackageRejected: if a git dependency is found.
    """
    pass


def _resolve_package_name(package: Package) -> str:
    """Resolve the package's real name based on its protocol.

    Non-registry deps might have names in their locator string that differ from the one in their
    package.json file.

    Look at the package.json name for every non-registry dependency.
    """
    return NotImplemented


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
    return NotImplemented
