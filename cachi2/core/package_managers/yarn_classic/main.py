import logging

import semver

from cachi2.core.errors import PackageManagerError
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, EnvironmentVariable, RequestOutput
from cachi2.core.package_managers.yarn.utils import run_yarn_cmd
from cachi2.core.package_managers.yarn_classic.resolver import resolve_packages
from cachi2.core.package_managers.yarn_classic.workspaces import extract_workspace_metadata
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


MIRROR_DIR = "deps/yarn-classic"


def fetch_yarn_source(request: Request) -> RequestOutput:
    """Process all the yarn source directories in a request."""
    components: list[Component] = []

    def _ensure_mirror_dir_exists(output_dir: RootedPath) -> None:
        output_dir.join_within_root(MIRROR_DIR).path.mkdir(parents=True, exist_ok=True)

    for package in request.yarn_classic_packages:
        package_path = request.source_dir.join_within_root(package.path)
        _ensure_mirror_dir_exists(request.output_dir)
        _resolve_yarn_project(package_path, request.output_dir)
        # Workspaces metadata is not used at the moment, but will
        # eventualy be converted into components. Using a noop assertion
        # to prevent linters from complaining.
        workspaces = extract_workspace_metadata(package_path)
        assert workspaces is not None  # nosec -- see comment above

    return RequestOutput.from_obj_list(
        components, _generate_build_environment_variables(), project_files=[]
    )


def _resolve_yarn_project(package_path: RootedPath, output_dir: RootedPath) -> None:
    """Process a request for a single yarn source directory."""
    log.info(f"Fetching the yarn dependencies at the subpath {package_path}")

    prefetch_env = _get_prefetch_environment_variables(output_dir)
    _verify_corepack_yarn_version(package_path, prefetch_env)
    _fetch_dependencies(package_path, prefetch_env)
    resolve_packages(package_path)


def _fetch_dependencies(source_dir: RootedPath, env: dict[str, str]) -> None:
    """Fetch dependencies using 'yarn install'.

    :param source_dir: the directory in which the yarn command will be called.
    :param env: environment variable mapping used for the prefetch.
    :raises PackageManagerError: if the 'yarn install' command fails.
    """
    run_yarn_cmd(
        [
            "install",
            "--disable-pnp",
            "--frozen-lockfile",
            "--ignore-engines",
            "--no-default-rc",
            "--non-interactive",
        ],
        source_dir,
        env,
    )


def _get_prefetch_environment_variables(output_dir: RootedPath) -> dict[str, str]:
    """Get environment variables that will be used for the prefetch."""
    return {
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
        "COREPACK_ENABLE_PROJECT_SPEC": "0",
        "YARN_IGNORE_PATH": "true",
        "YARN_IGNORE_SCRIPTS": "true",
        "YARN_YARN_OFFLINE_MIRROR": str(output_dir.join_within_root(MIRROR_DIR)),
        "YARN_YARN_OFFLINE_MIRROR_PRUNING": "false",
    }


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


def _verify_corepack_yarn_version(source_dir: RootedPath, env: dict[str, str]) -> None:
    """Verify that corepack installed the correct version of yarn by checking `yarn --version`."""
    yarn_version_output = run_yarn_cmd(["--version"], source_dir, env=env).strip()

    try:
        installed_yarn_version = semver.version.Version.parse(yarn_version_output)
    except ValueError as e:
        raise PackageManagerError(
            "The command `yarn --version` did not return a valid semver."
        ) from e

    min_version_inclusive = semver.version.Version(1, 22, 0)
    max_version_exclusive = semver.version.Version(2, 0, 0)

    if (
        installed_yarn_version < min_version_inclusive
        or installed_yarn_version >= max_version_exclusive
    ):
        raise PackageManagerError(
            "Cachi2 expected corepack to install yarn >=1.22.0,<2.0.0, but instead "
            f"found yarn@{yarn_version_output}."
        )

    log.info("Processing the request using yarn@%s", yarn_version_output)
