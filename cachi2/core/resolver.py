from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from cachi2.core.errors import UnsupportedFeature
from cachi2.core.models.input import PackageManagerType, Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.package_managers import gomod, npm, pip, yarn
from cachi2.core.rooted_path import RootedPath
from cachi2.core.utils import copy_directory

Handler = Callable[[Request], RequestOutput]

_package_managers: dict[PackageManagerType, Handler] = {
    "gomod": gomod.fetch_gomod_source,
    "npm": npm.fetch_npm_source,
    "pip": pip.fetch_pip_source,
    "yarn": yarn.fetch_yarn_source,
}

# This is where we put package managers currently under development in order to
# invoke them via CLI
_dev_package_managers: dict[PackageManagerType, Handler] = {}

# This is *only* used to provide a list for `cachi2 --version`
supported_package_managers = list(_package_managers)


def resolve_packages(request: Request) -> RequestOutput:
    """
    Resolve all packages specified in a request.

    This function performs the operations in a working copy of the source directory in case
    a package manager that can make unwanted modifications will be used.
    """
    if not request.yarn_packages:
        return _resolve_packages(request)
    else:
        original_source_dir = request.source_dir

        with TemporaryDirectory(".cachi2-source-copy", dir=".") as temp_dir:
            source_backup = copy_directory(original_source_dir.path, Path(temp_dir).resolve())

            request.source_dir = RootedPath(source_backup)
            output = _resolve_packages(request)
            request.source_dir = original_source_dir

            return output


def _resolve_packages(request: Request) -> RequestOutput:
    """Run all requested package managers, return their combined output."""
    _supported_package_managers = _package_managers
    requested_types = set(pkg.type for pkg in request.packages)
    if "dev-package-managers" in request.flags:
        _supported_package_managers = _package_managers | _dev_package_managers
    unsupported_types = requested_types - _supported_package_managers.keys()
    if unsupported_types:
        raise UnsupportedFeature(
            f"Package manager(s) not yet supported: {', '.join(sorted(unsupported_types))}",
            # unknown package managers shouldn't get past input validation
            solution="But the good news is that we're already working on it!",
        )
    pkg_managers = [_supported_package_managers[type_] for type_ in sorted(requested_types)]
    return _merge_outputs(pkg_manager(request) for pkg_manager in pkg_managers)


def _merge_outputs(outputs: Iterable[RequestOutput]) -> RequestOutput:
    """Merge RequestOutput instances."""
    components = []
    env_vars = []
    project_files = []

    for output in outputs:
        components.extend(output.components)
        env_vars.extend(output.build_config.environment_variables)
        project_files.extend(output.build_config.project_files)

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=env_vars,
        project_files=project_files,
    )
