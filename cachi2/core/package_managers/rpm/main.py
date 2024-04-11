import logging

from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.models.sbom import Component

log = logging.getLogger(__name__)


def fetch_rpm_source(request: Request) -> RequestOutput:
    """Process all the rpm source directories in a request."""
    components: list[Component] = []
    for package in request.rpm_packages:
        _ = request.source_dir.join_within_root(package.path)

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=[],
        project_files=[],
    )
