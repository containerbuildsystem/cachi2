import logging

import yaml
from pydantic import ValidationError

from cachi2.core.errors import PackageManagerError, PackageRejected
from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.rpm.redhat import RedhatRpmsLock
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


DEFAULT_LOCKFILE_NAME = "rpms.lock.yaml"
DEFAULT_PACKAGE_DIR = "deps/rpm"

# during the computing of file checksum read chunk of size 1 MB
READ_CHUNK = 1048576


def fetch_rpm_source(request: Request) -> RequestOutput:
    """Process all the rpm source directories in a request."""
    components: list[Component] = []
    for package in request.rpm_packages:
        path = request.source_dir.join_within_root(package.path)
        components.extend(_resolve_rpm_project(path, request.output_dir))

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=[],
        project_files=[],
    )


def _resolve_rpm_project(source_dir: RootedPath, output_dir: RootedPath) -> list[Component]:
    """
    Process a request for a single RPM source directory.

    Process the input lockfile, fetch packages and generate SBOM.
    """
    # Check the availability of the input lockfile.
    if not source_dir.join_within_root(DEFAULT_LOCKFILE_NAME).path.exists():
        raise PackageRejected(
            f"RPM lockfile '{DEFAULT_LOCKFILE_NAME}' missing, refusing to continue.",
            solution=(
                "Make sure your repository has RPM lockfile '{DEFAULT_LOCKFILE_NAME}' checked in "
                "to the repository."
            ),
        )

    lockfile_name = source_dir.join_within_root(DEFAULT_LOCKFILE_NAME)
    log.info(f"Reading RPM lockfile: {lockfile_name}")
    with open(lockfile_name) as f:
        try:
            yaml_content = yaml.safe_load(f)
        except yaml.YAMLError as e:
            log.error(str(e))
            raise PackageRejected(
                f"RPM lockfile '{DEFAULT_LOCKFILE_NAME}' yaml format is not correct.",
                solution=("Check correct 'yaml' syntax in the lockfile."),
            )

        log.debug("Validating lockfile.")
        try:
            _ = RedhatRpmsLock.model_validate(yaml_content)
        except ValidationError as e:
            loc = e.errors()[0]["loc"]
            msg = e.errors()[0]["msg"]
            raise PackageManagerError(
                f"RPM lockfile '{DEFAULT_LOCKFILE_NAME}' format is not valid: '{loc}: {msg}'",
                solution=(
                    "Check the correct format and whether any keys are missing in the lockfile."
                ),
            )

        _ = output_dir.join_within_root(DEFAULT_PACKAGE_DIR)
        components: list[Component] = []
        return components
