import logging
import re
from collections import defaultdict
from functools import partial
from pathlib import Path
from typing import Iterable, Optional, Union

from cachi2.core.errors import PackageRejected
from cachi2.core.models.input import PackageInput, Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.package_managers import yarn, yarn_classic
from cachi2.core.resolver import _merge_outputs
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


def _get_path_to_yarn_lock(
    package: PackageInput,
    source_dir: RootedPath,
) -> Path:
    """Construct a path to package's lockfile.

    Raise an exception when there is no lockfile.
    """
    yarnlock_path = source_dir.join_within_root("yarn.lock")
    if yarnlock_path.path.exists():
        return yarnlock_path.path

    raise PackageRejected(f"Yarn lockfile is missing in {package.path}", solution=None)


def _contains_yarn_version_trait(
    package: PackageInput,
    source_dir: RootedPath,
    trait_pattern: re.Pattern[str],
) -> Optional[re.Match[str]]:
    text = _get_path_to_yarn_lock(package, source_dir).read_text()
    return trait_pattern.search(text)


_yarn_classic_pattern = re.compile("yarn lockfile v1")  # See [yarn_classic_trait].
_yarnberry_pattern = re.compile("__metadata:")  # See [yarnberry_trait] and [yarn_v2_test_repo].
contains_yarn_classic = partial(_contains_yarn_version_trait, trait_pattern=_yarn_classic_pattern)
contains_yarnberry = partial(_contains_yarn_version_trait, trait_pattern=_yarnberry_pattern)

_yarn_versions = {
    "yarn_classic": contains_yarn_classic,
    "yarnberry": contains_yarnberry,
}
_yarn_processors = {
    "yarn_classic": yarn_classic.fetch_yarn_source,
    "yarnberry": yarn.fetch_yarn_source,
}


def _yarn_selector(
    package: PackageInput,
    source_dir: RootedPath,
) -> tuple[str, Optional[Exception]]:
    try:
        for yarn_version, version_matches_for in _yarn_versions.items():
            if version_matches_for(package, source_dir):
                return yarn_version, None
        else:
            return "uncategorized", None
    except Exception as e:
        return "exception", e


def _separate_packages_by_yarn_version(
    packages: Iterable[PackageInput],
    source_dir: RootedPath,
) -> dict[str, Union[list[PackageInput], tuple[PackageInput, Exception]]]:
    """Sorts packages to bins depending on which Yarn version was used.

    The output dictionary contains "uncategorized" entry to capture anything
    that could not be categorized (likely yet-unsupported versions of Yarn).

    The output dictionary also contains category "exceptions" to accumulate
    exceptions that occured during pre-processing of packages.
    """
    output = defaultdict(list)
    for p in packages:
        category, exception = _yarn_selector(p, source_dir)
        if exception is None:
            output[category].append(p)
        else:  # This is an exceptional result.
            # Categories will never clash, but mypy does not know that and
            # does not want to learn.
            output[category].append((p, exception))  # type: ignore
    return output  # type: ignore


def dispatch_to_correct_fetcher(request: Request) -> RequestOutput:
    """Dispatch a request to correct yarn backend.

    In order to save a user from the need to distinguish between different
    flavors of Yarn this function attempts to separate Yarn packages and process each
    with an appropriate manager.
    """
    sorted_packages = _separate_packages_by_yarn_version(request.packages, request.source_dir)
    if uncat := sorted_packages.pop("uncategorized", False):
        log.warning(f"Failed to categorize the following packages: {uncat}")
    if exceptions := sorted_packages.pop("exceptions", False):
        log.warning(f"Following packages caused categorizer to fail: {exceptions}")

    fetched_packages = []
    for pm, packages in sorted_packages.items():
        new_request = request.model_copy(update={"packages": packages})
        fetched_packages.append(_yarn_processors[pm](new_request))
    # Judging from the resolver code it is safe to merge multiple packages.
    # Moreover, it does not look like there is any mechanism in place now to
    # prevent users from requesting both PMs simultaneously.
    # The code below preserves this behavior.
    return _merge_outputs(fetched_packages)


# References
# [yarn_classic_trait]:  https://github.com/yarnpkg/berry/blob/13d5b3041794c33171808fdce635461ff4ab5c4e/packages/yarnpkg-core/sources/Project.ts#L434
# [yarnberry_trait]:  https://github.com/yarnpkg/berry/blob/13d5b3041794c33171808fdce635461ff4ab5c4e/packages/yarnpkg-core/sources/Project.ts#L374
# [yarn_v2_test_repo]:  https://github.com/cachito-testing/cachi2-yarn-berry/blob/70515793108df42547d3320c7ea4cd6b6e505c46/yarn.lock
