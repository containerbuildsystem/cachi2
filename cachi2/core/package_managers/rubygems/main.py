import logging
from typing import Any, Optional

from cachi2.core.models.input import Request
from cachi2.core.models.output import EnvironmentVariable, ProjectFile, RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.rubygems.parser import (
    BundlerDependency,
    GemDependency,
    GitDependency,
    PathDependency,
)
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)

RUBYGEMS_URL = "https://rubygems.org"


def fetch_rubygems_source(request: Request) -> RequestOutput:
    """Resolve and process all rubygems packages."""
    components: list[Component] = []
    environment_variables: list[EnvironmentVariable] = []
    project_files: list[ProjectFile] = []

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=environment_variables,
        project_files=project_files,
    )


def _resolve_rubygems(package_dir: RootedPath, output_dir: RootedPath) -> list[Component]:
    """TODO."""
    return NotImplemented


def _get_package_metadata(
    package_dir: RootedPath,
    path_dependencies: list[PathDependency],
) -> tuple[str, Optional[str]]:
    """TODO."""
    return NotImplemented


def _get_repository_name(package_dir: RootedPath) -> str:
    """TODO."""
    return NotImplemented


def _download_dependencies(
    output_dir: RootedPath,
    dependencies: list[BundlerDependency],
) -> list[dict[str, Any]]:
    """TODO."""
    return NotImplemented


def _download_rubygems_package(output_dir: RootedPath, gem: GemDependency) -> dict[str, Any]:
    """TODO."""
    return NotImplemented


def _download_git_package(output_dir: RootedPath, gem: GitDependency) -> dict[str, Any]:
    """
    TODO.

    # directory has a specific format: {repository_name}-{revision}
    # revision must have 12 characters
    # https://github.com/rubygems/rubygems/blob/3da9b1dda0824d1d770780352bb1d3f287cb2df5/bundler/lib/bundler/source/git.rb#L327
    """
    return NotImplemented


def _bundle_config_exists(package_dir: RootedPath) -> bool:
    """TODO."""
    return NotImplemented


def _generate_environment_variables() -> list[EnvironmentVariable]:
    """TODO."""
    return NotImplemented


def _generate_purl_for(gem: BundlerDependency) -> str:
    """TODO."""
    return NotImplemented
