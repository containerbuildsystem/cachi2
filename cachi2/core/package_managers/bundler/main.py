import logging
import os
from pathlib import Path
from textwrap import dedent
from typing import Optional

from packageurl import PackageURL

from cachi2.core.errors import PackageRejected, UnsupportedFeature
from cachi2.core.models.input import Request
from cachi2.core.models.output import EnvironmentVariable, ProjectFile, RequestOutput
from cachi2.core.models.property_semantics import PropertySet
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.bundler.parser import (
    GemPlatformSpecificDependency,
    ParseResult,
    PathDependency,
    parse_lockfile,
)
from cachi2.core.rooted_path import RootedPath
from cachi2.core.scm import get_repo_id

log = logging.getLogger(__name__)

CONFIG_OVERRIDE = "bundler/config_override"


def fetch_bundler_source(request: Request) -> RequestOutput:
    """Resolve and process all bundler packages."""
    components: list[Component] = []
    environment_variables: list[EnvironmentVariable] = (
        _prepare_environment_variables_for_hermetic_build()
    )
    project_files: list[ProjectFile] = []

    for package in request.bundler_packages:
        path_within_root = request.source_dir.join_within_root(package.path)
        components.extend(
            _resolve_bundler_package(
                package_dir=path_within_root,
                output_dir=request.output_dir,
                allow_binary=package.allow_binary,
            )
        )
        project_files.append(_prepare_for_hermetic_build(request.source_dir, request.output_dir))

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=environment_variables,
        project_files=project_files,
    )


def _resolve_bundler_package(
    package_dir: RootedPath,
    output_dir: RootedPath,
    allow_binary: bool = False,
) -> list[Component]:
    """Process a request for a single bundler package."""
    deps_dir = output_dir.join_within_root("deps", "bundler")
    deps_dir.path.mkdir(parents=True, exist_ok=True)
    dependencies = parse_lockfile(package_dir, allow_binary)

    name, version = _get_main_package_name_and_version(package_dir, dependencies)
    vcs_url = get_repo_id(package_dir.root).as_vcs_url_qualifier()
    main_package_purl = PackageURL(
        type="gem",
        name=name,
        version=version,
        qualifiers={"vcs_url": vcs_url},
        subpath=str(package_dir.subpath_from_root),
    )

    components = [Component(name=name, version=version, purl=main_package_purl.to_string())]
    for dep in dependencies:
        dep.download_to(deps_dir)
        if isinstance(dep, GemPlatformSpecificDependency):
            properties = PropertySet(bundler_package_binary=True).to_properties()
        else:
            properties = []

        c = Component(name=dep.name, version=dep.version, purl=dep.purl, properties=properties)
        components.append(c)

    return components


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
        if isinstance(dep, PathDependency) and dep.subpath == ".":
            return dep.name, dep.version

    return None


def _get_repo_name_from_origin_remote(package_dir: RootedPath) -> str:
    """Extract repository name from git origin remote in the package directory."""
    repo_path = get_repo_id(package_dir.root).parsed_origin_url.path
    repo_name = Path(repo_path).stem

    resolved_path = Path(repo_name).joinpath(package_dir.subpath_from_root)
    return str(resolved_path)


def _prepare_environment_variables_for_hermetic_build() -> list[EnvironmentVariable]:
    return [
        # Contains path to a directory where a new config could be found.
        EnvironmentVariable(name="BUNDLE_APP_CONFIG", value="${output_dir}/" + CONFIG_OVERRIDE),
    ]


def _prepare_for_hermetic_build(source_dir: RootedPath, output_dir: RootedPath) -> ProjectFile:
    """Prepare a package for hermetic build by injecting necessary config."""
    potential_bundle_config = source_dir.join_within_root(".bundle/config").path
    hermetic_config = dedent(
        """
        BUNDLE_CACHE_PATH: "${output_dir}/deps/bundler"
        BUNDLE_DEPLOYMENT: "true"
        BUNDLE_NO_PRUNE: "true"
        BUNDLE_VERSION: "system"
    """
    )
    if potential_bundle_config.is_file():
        config_data = potential_bundle_config.read_text()
        config_data += hermetic_config
    elif (alternative_config := os.getenv("BUNDLE_APP_CONFIG")) is not None:
        # Corner case: a user decides to define their own alternate config.
        # In this scenario cachi2 must try to copy over user-defined variables
        # to its overriding alternate config.
        config_data = Path(alternative_config, "config").read_text()
        config_data += hermetic_config
    else:
        config_data = hermetic_config
    overriding_bundler_config_path = output_dir.join_within_root(CONFIG_OVERRIDE, "config").path
    return ProjectFile(abspath=overriding_bundler_config_path, template=config_data)
