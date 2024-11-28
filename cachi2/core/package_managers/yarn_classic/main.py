import logging
import re
from collections import Counter
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from cachi2.core.errors import PackageManagerError, PackageRejected
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, EnvironmentVariable, RequestOutput
from cachi2.core.package_managers.yarn.utils import (
    VersionsRange,
    extract_yarn_version_from_env,
    run_yarn_cmd,
)
from cachi2.core.package_managers.yarn_classic.project import Project
from cachi2.core.package_managers.yarn_classic.resolver import (
    GitPackage,
    RegistryPackage,
    UrlPackage,
    YarnClassicPackage,
    resolve_packages,
)
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
        _resolve_yarn_project(Project.from_source_dir(package_path), request.output_dir)

    return RequestOutput.from_obj_list(
        components, _generate_build_environment_variables(), project_files=[]
    )


def _resolve_yarn_project(project: Project, output_dir: RootedPath) -> None:
    """Process a request for a single yarn source directory."""
    log.info(f"Fetching the yarn dependencies at the subpath {project.source_dir}")

    _verify_repository(project)
    prefetch_env = _get_prefetch_environment_variables(output_dir)
    _verify_corepack_yarn_version(project.source_dir, prefetch_env)
    _fetch_dependencies(project.source_dir, prefetch_env)
    packages = resolve_packages(project)
    _verify_no_offline_mirror_collisions(packages)


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


def _reject_if_pnp_install(project: Project) -> None:
    if project.is_pnp_install:
        raise PackageRejected(
            reason=("Yarn PnP install detected; PnP installs are unsupported by cachi2"),
            solution=(
                "Please convert your project to a regular install-based one.\n"
                "If you use Yarn's PnP, please remove `installConfig.pnp: true`"
                " from 'package.json', any file(s) with glob name '*.pnp.cjs',"
                " and any 'node_modules' directories."
            ),
        )


def _verify_repository(project: Project) -> None:
    _reject_if_pnp_install(project)
    # _check_lockfile(project)


def _verify_corepack_yarn_version(source_dir: RootedPath, env: dict[str, str]) -> None:
    """Verify that corepack installed the correct version of yarn by checking `yarn --version`."""
    installed_yarn_version = extract_yarn_version_from_env(source_dir, env)

    if installed_yarn_version not in VersionsRange("1.22.0", "2.0.0"):
        raise PackageManagerError(
            "Cachi2 expected corepack to install yarn >=1.22.0,<2.0.0, but instead "
            f"found yarn@{installed_yarn_version}."
        )

    log.info("Processing the request using yarn@%s", installed_yarn_version)


def _verify_no_offline_mirror_collisions(packages: Iterable[YarnClassicPackage]) -> None:
    """Verify that there are no duplicate tarballs in the offline mirror."""
    tarballs = []
    for p in packages:
        if isinstance(p, (RegistryPackage, UrlPackage)):
            tarball_name = _get_tarball_mirror_name(p.url)
            tarballs.append(tarball_name)
        elif isinstance(p, GitPackage):
            tarball_name = _get_git_tarball_mirror_name(p.url)
            tarballs.append(tarball_name)
        else:
            # file, link, and workspace packages are not copied to the offline mirror
            continue

    c = Counter(tarballs)
    duplicate_tarballs = [f"{name} ({count}x)" for name, count in c.most_common() if count > 1]
    if len(duplicate_tarballs) > 0:
        raise PackageManagerError(f"Duplicate tarballs detected: {', '.join(duplicate_tarballs)}")


# https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/fetchers/tarball-fetcher.js#L21
RE_URL_NAME_MATCH = r"/(?:(@[^/]+)(?:\/|%2f))?[^/]+/(?:-|_attachments)/(?:@[^/]+\/)?([^/]+)$"


# https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/fetchers/tarball-fetcher.js#L65
def _get_tarball_mirror_name(url: str) -> str:
    parsed_url = urlparse(url)
    path = Path(parsed_url.path)

    match = re.search(RE_URL_NAME_MATCH, str(path))

    if match is not None:
        scope, tarball_basename = match.groups()
        package_filename = f"{scope}-{tarball_basename}" if scope else tarball_basename
    else:
        package_filename = path.name

    return package_filename


# https://github.com/yarnpkg/yarn/blob/7cafa512a777048ce0b666080a24e80aae3d66a9/src/fetchers/git-fetcher.js#L40
def _get_git_tarball_mirror_name(url: str) -> str:
    parsed_url = urlparse(url)
    path = Path(parsed_url.path)

    package_filename = path.name
    hash = parsed_url.fragment

    if hash:
        package_filename = f"{package_filename}-{hash}"

    if package_filename.startswith(":"):
        package_filename = package_filename[1:]

    return package_filename
