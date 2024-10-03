from cachi2.core.errors import PackageRejected
from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.rooted_path import RootedPath

DEFAULT_LOCKFILE_NAME = "cachi2_generic.yaml"
DEFAULT_DEPS_DIR = "deps/generic"


def fetch_generic_source(request: Request) -> RequestOutput:
    """
    Resolve and fetch generic dependencies for a given request.

    :param request: the request to process
    """
    components = []
    for package in request.generic_packages:
        path = request.source_dir.join_within_root(package.path)
        components.extend(_resolve_generic_lockfile(path, request.output_dir))
    return RequestOutput.from_obj_list(components=components)


def _resolve_generic_lockfile(source_dir: RootedPath, output_dir: RootedPath) -> list[Component]:
    if not source_dir.join_within_root(DEFAULT_LOCKFILE_NAME).path.exists():
        raise PackageRejected(
            f"Cachi2 generic lockfile '{DEFAULT_LOCKFILE_NAME}' missing, refusing to continue.",
            solution=(
                f"Make sure your repository has cachi2 generic lockfile '{DEFAULT_LOCKFILE_NAME}' checked in "
                "to the repository."
            ),
        )
    return []
