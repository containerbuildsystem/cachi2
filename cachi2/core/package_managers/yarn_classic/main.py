import logging

from cachi2.core.models.output import Component, EnvironmentVariable
from cachi2.core.package_managers.yarn.project import Project
from cachi2.core.package_managers.yarn.main import _verify_repository
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(name=__name__)


def _verify_repository(project: Project) -> None:
    _check_for_pnp(project)
    _check_lockfile(project)


def _resolve_yarn_project(project: Project, output_dir: RootedPath) -> list[Component]:
    """Process a request for a single yarn source directory.

    :param project: the directory to be processed.
    :param output_dir: the directory where the prefetched dependencies will be placed.
    :raises PackageManagerError: if fetching dependencies fails
    """
    log.info(f"Fetching the yarn-classic dependencies at the subpath {project.source_dir}")

    _verify_repository(project)

    # Placeholders for implementations in other PRs
    # _set_yarnrc_configuration(project, output_dir)
    # packages = resolve_packages(project.source_dir)
    # _fetch_dependencies(project.source_dir)

    # return create_components(packages, project, output_dir)


def _generate_build_environment_variables() -> list[EnvironmentVariable]:
    """Generate environment variables that will be used for building the project.

    These ensure that yarnv1 will
    - YARN_YARN_OFFLINE_MIRROR: Maintain offline copies of packages for repeatable and reliable
        builds. Defines the cache location.
    - YARN_YARN_OFFLINE_MIRROR_PRUNING: Control automatic pruning of the offline mirror. We
        disable this, as we need to retain the cache.
    """
    env_vars = {
        "YARN_YARN_OFFLINE_MIRROR": "${output_dir}/deps/yarn-classic",
        "YARN_YARN_OFFLINE_MIRROR_PRUNING": "false",
    }

    return [EnvironmentVariable(name=key, value=value) for key, value in env_vars.items()]
