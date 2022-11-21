# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import pathlib
from typing import Any

from cachi2.core.config import get_worker_config

log = logging.getLogger(__name__)


# Similar with cachito.common.paths.RequestBundleDir, this base type will be the
# correct type for Linux or Windows individually.
base_path: Any = type(pathlib.Path())


class SourcesDir(base_path):
    """
    Represents a sources directory tree for a package.

    The directory will be created automatically when this object is instantiated.

    :param str repo_name: a namespaced repository name of package. For example,
        ``release-engineering/retrodep``.
    :param str ref: the revision reference used to construct archive filename.
    """

    def __new__(cls, repo_name, ref):
        """Create a new Path object."""
        self = super().__new__(cls, get_worker_config().cachito_sources_dir)

        repo_relative_dir = pathlib.Path(*repo_name.split("/"))
        self.package_dir = self.joinpath(repo_relative_dir)
        self.archive_path = self.joinpath(repo_relative_dir, f"{ref}.tar.gz")

        log.debug("Ensure directory %s exists.", self.package_dir)
        self.package_dir.mkdir(parents=True, exist_ok=True)

        return self
