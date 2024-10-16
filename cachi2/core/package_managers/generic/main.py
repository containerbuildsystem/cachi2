import asyncio
import logging
from pathlib import Path
from typing import List

import yaml
from pydantic import ValidationError

from cachi2.core.checksum import must_match_any_checksum
from cachi2.core.config import get_config
from cachi2.core.errors import PackageRejected
from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.general import async_download_files
from cachi2.core.package_managers.generic.models import GenericArtifact, GenericLockfileV1
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath

log = logging.getLogger(__name__)
DEFAULT_LOCKFILE_NAME = "generic_lockfile.yaml"
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
    """
    Resolve the generic lockfile and pre-fetch the dependencies.

    :param source_dir: the source directory to resolve the lockfile from
    :param output_dir: the output directory to store the dependencies
    """
    lockfile_path = source_dir.join_within_root(DEFAULT_LOCKFILE_NAME)
    if not lockfile_path.path.exists():
        raise PackageRejected(
            f"Cachi2 generic lockfile '{DEFAULT_LOCKFILE_NAME}' missing, refusing to continue.",
            solution=(
                f"Make sure your repository has cachi2 generic lockfile '{DEFAULT_LOCKFILE_NAME}' checked in "
                "to the repository."
            ),
        )

    log.info(f"Reading generic lockfile: {lockfile_path}")
    lockfile = _load_lockfile(lockfile_path)
    artifacts: List[GenericArtifact] = [
        GenericArtifact.from_lockfile_artifact(a) for a in lockfile.artifacts
    ]

    # output_dir is now the root and cannot be escaped
    output_dir = output_dir.re_root(DEFAULT_DEPS_DIR)

    for artifact in artifacts:
        log.debug(f"Resolving artifact: {artifact.download_url}")
        # make sure target does not point outside the output directory
        try:
            destination = output_dir.join_within_root(artifact.resolved_target)
        except PathOutsideRoot as e:
            e.solution = (
                f"Artifact '{artifact.download_url}' has target which falls "
                "outside of the dependencies root. Refusing to proceed."
            )
            raise

        # make sure that targets do not overlap
        if any([a.has_same_resolved_path(destination) for a in artifacts]):
            raise PackageRejected(
                f"More than one file from {lockfile_path} is trying to write to the same target: {destination}",
                solution="Make sure that all targets are unique.",
            )

        # create the parent directory and assign the resolved path to the artifact
        Path.mkdir(destination.path.parent, parents=True, exist_ok=True)
        artifact.resolved_path = destination

    # disable mypy check to avoid type error on resolved_path being able to be None,
    # because it is always set in the loop above. Same for checksum verification.
    asyncio.run(
        async_download_files(
            {a.download_url: a.resolved_path for a in artifacts}, get_config().concurrency_limit  # type: ignore
        )
    )

    # verify checksums
    for artifact in artifacts:
        must_match_any_checksum(artifact.resolved_path, artifact.formatted_checksums)  # type: ignore
    return []


def _load_lockfile(lockfile_path: RootedPath) -> GenericLockfileV1:
    """
    Load the cachi2 generic lockfile from the given path.

    :param lockfile_path: the path to the lockfile
    """
    with open(lockfile_path, "r") as f:
        try:
            lockfile_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise PackageRejected(
                f"Cachi2 lockfile '{lockfile_path}' yaml format is not correct: {e}",
                solution="Check correct 'yaml' syntax in the lockfile.",
            )

        try:
            lockfile = GenericLockfileV1.model_validate(lockfile_data)
        except ValidationError as e:
            loc = e.errors()[0]["loc"]
            msg = e.errors()[0]["msg"]
            raise PackageRejected(
                f"Cachi2 lockfile '{lockfile_path}' format is not valid: '{loc}: {msg}'",
                solution=(
                    "Check the correct format and whether any keys are missing in the lockfile."
                ),
            )
    return lockfile
