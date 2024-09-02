from cachi2.core.models.input import Request
from cachi2.core.models.output import EnvironmentVariable, ProjectFile, RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.bundler.parser import parse_lockfile
from cachi2.core.rooted_path import RootedPath


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
    parse_lockfile(package_dir)
    return []
