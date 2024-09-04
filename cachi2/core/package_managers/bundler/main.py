import logging
from pathlib import Path
from typing import Optional

from cachi2.core.errors import PackageRejected, UnsupportedFeature
from cachi2.core.models.input import Request
from cachi2.core.models.output import EnvironmentVariable, ProjectFile, RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.bundler.parser import ParseResult, PathDependency, parse_lockfile
from cachi2.core.rooted_path import RootedPath
from cachi2.core.scm import get_repo_id

log = logging.getLogger(__name__)


def fetch_bundler_source(request: Request) -> RequestOutput:
    """Resolve and process all bundler packages."""
    components: list[Component] = []
    environment_variables: list[EnvironmentVariable] = []
    project_files: list[ProjectFile] = []

    for package in request.packages:
        path_within_root = request.source_dir.join_within_root(package.path)
        _resolve_bundler_package(package_dir=path_within_root, output_dir=request.output_dir)

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=environment_variables,
        project_files=project_files,
    )


def _resolve_bundler_package(package_dir: RootedPath, output_dir: RootedPath) -> list[Component]:
    """Process a request for a single bundler package."""
    dependencies = parse_lockfile(package_dir)
    _get_main_package_name_and_version(package_dir, dependencies)
    return []


def _get_main_package_name_and_version(
    package_dir: RootedPath,
    dependencies: ParseResult,
) -> tuple[str, Optional[str]]:
    """
    Get main package name and version.

    The main package is the package that is being processed by cachi2.
    Not any of its dependencies.
    """
    name_and_version = _get_name_and_version_from_lockfile(dependencies)
    if name_and_version is not None:
        return name_and_version

    log.info("Failed to extract name and version from gemspec file")

    # fallback to origin remote
    try:
        name = _get_repo_name_from_origin_remote(package_dir)
    # if the git repository does not have an origin remote
    except UnsupportedFeature:
        raise PackageRejected(
            reason="Failed to extract package name from origin remote",
            solution=(
                "Please specify package name and version in a way that Cachi2 understands,\n"
                "or make sure that the directory Cachi2 is processing is a git repository with\n"
                "an 'origin' remote, in which case Cachi2 will infer the package name from the remote URL."
            ),
        )

    return name, None


def _get_name_and_version_from_lockfile(dependencies: ParseResult) -> Optional[tuple[str, str]]:
    """
    Extract the package name and version from dependencies in the Gemfile.lock.

    Gemfile.lock only contains the name and version of the package. If the gemspec file
    is explicitly defined in the Gemfile, Bundler will create a path dependency record
    representing the gem in the package directory.

    Note that having a gemspec file is an edge case when the package is not an actual gem.
    But it is possible to include a gemspec file in the package directory that defines its name,
    version, and other metadata even if the package is not a gem. So we respect this edge case.

    See design doc for more details:
    https://github.com/containerbuildsystem/cachi2/blob/main/docs/design/bundler.md
    """
    for dep in dependencies:
        if isinstance(dep, PathDependency) and dep.path == ".":
            return dep.name, dep.version

    return None


def _get_repo_name_from_origin_remote(package_dir: RootedPath) -> str:
    """Extract repository name from git origin remote in the package directory."""
    repo_path = get_repo_id(package_dir.root).parsed_origin_url.path
    repo_name = Path(repo_path).stem

    resolved_path = Path(repo_name).joinpath(package_dir.subpath_from_root)
    return str(resolved_path)
