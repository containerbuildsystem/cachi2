from collections.abc import Iterable
from typing import Callable

from cachi2.core.errors import UnsupportedFeature
from cachi2.core.models.input import PackageManagerType, Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.package_managers import cargo, gomod, npm, pip

Handler = Callable[[Request], RequestOutput]

_package_managers: dict[PackageManagerType, Handler] = {
    "gomod": gomod.fetch_gomod_source,
    "npm": npm.fetch_npm_source,
    "pip": pip.fetch_pip_source,
    "cargo": cargo.fetch_cargo_source,
}


supported_package_managers = list(_package_managers)


def resolve_packages(request: Request) -> RequestOutput:
    """Run all requested package managers, return their combined output."""
    requested_types = set(pkg.type for pkg in request.packages)
    unsupported_types = requested_types - _package_managers.keys()
    if unsupported_types:
        raise UnsupportedFeature(
            f"Package manager(s) not yet supported: {', '.join(sorted(unsupported_types))}",
            # unknown package managers shouldn't get past input validation
            solution="But the good news is that we're already working on it!",
        )
    pkg_managers = [_package_managers[type_] for type_ in sorted(requested_types)]
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
