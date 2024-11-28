from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.package_managers import yarn, yarn_classic
from cachi2.core.package_managers.yarn_classic.main import MissingLockfile, NotV1Lockfile
from cachi2.core.resolver import _merge_outputs


def fetch_yarn_source(request: Request) -> RequestOutput:
    """Fetch yarn source."""
    # Packages could be a mixture of yarn v1 and v2 (at least this is how it
    # looks now). To preserve this behavior each reqiest is split into individual
    # packages which are assessed one by one.
    fetched_packages = []
    for package in request.packages:
        new_request = request.model_copy(update={"packages": [package]})
        try:
            fetched_packages.append(yarn_classic.fetch_yarn_source(new_request))
        except (MissingLockfile, NotV1Lockfile):
            # It is assumed that if a package is not v1 then it is probably v2.
            fetched_packages.append(yarn.fetch_yarn_source(new_request))
    return _merge_outputs(fetched_packages)
