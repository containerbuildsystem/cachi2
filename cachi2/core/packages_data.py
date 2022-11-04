# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

log = logging.getLogger(__name__)

# TODO: delete the whole module (RequestOutput does the same thing)


def _package_sort_key(package: Dict[str, Any]) -> Tuple[str, bool, str, Optional[str]]:
    """Return the sort key for sorting packages.

    :param package: a mapping representing a package information. It must
        contain four keys, type, dev, name and version.
    :type package: dict[str, any]
    :return: a four-elements tuple as the sort key in the order of type, dev,
        name and version.
    :rtype: tuple[str, bool, str, str]
    """
    return (
        package["type"],
        package.get("dev", False),
        package["name"],
        package["version"],
    )


def _package_equal(left: Union[Dict[str, Any], None], right: Dict[str, Any]) -> bool:
    """Check if left package equals to the right.

    Used by unique_packages internally.
    """
    if left is None:
        return False
    return (
        left["name"] == right["name"]
        and left["type"] == right["type"]
        and left["version"] == right["version"]
        and left.get("dev", False) == right.get("dev", False)
    )


def unique_packages(packages: List[Dict[str, Any]]) -> Iterator:
    """Remove duplicate packages.

    If two packages as well as dependencies have same name, type, version and
    dev, they are duplicated. This function assumes the packages have been
    sorted already.

    :param packages: a list of sorted packages to be deduplicated. If two
        packages have same name, type, version and dev, they will be considered
        as duplicate package.
    :type packages: list[dict[str, any]]
    """
    i = -1
    j = 0
    while j < len(packages):
        left = None if i < 0 else packages[i]
        right = packages[j]
        if _package_equal(left, right):
            j += 1
        else:
            yield right
            i = j
            j += 1


class PackagesData:
    """A collection of resolved packages."""

    def __init__(self) -> None:
        """Initialize an empty PackagesData instance."""
        self._index: Set[Tuple[str, str, str]] = set()
        self._packages: List[Dict[str, Any]] = []

    @property
    def packages(self) -> List[Dict[str, Any]]:
        """Get added packages."""
        return self._packages

    @property
    def all_dependencies(self) -> List[Dict[str, Any]]:
        """Gather dependencies together from every package.

        :return: a list of sorted and deduplicated dependencies gathered from
            every package. If no package is added, an empty list will be returned.
        :rtype: list[dict[str, any]]
        """
        return list(
            unique_packages(
                sorted(
                    (dep for pkg in self._packages for dep in pkg["dependencies"]),
                    key=_package_sort_key,
                )
            )
        )

    def add_package(self, pkg_info: Dict[str, str], path: str, deps: List[Dict[str, Any]]) -> None:
        """Add a package with deps.

        :param dict[str, str] pkg_info: a mapping containing package information.
            It must have ``name``, ``type`` and ``version`` key/value pairs.
        :param str path: the path where the package is retrieved. Consult with the
            ``fetch_*_source`` for the detailed information about a package's path.
        :param deps: a list of dependencies the package has.
        :type deps: list[dict[str, any]]
        :raises ValueError: if there is a package with same name, type and version
            has been added already.
        """
        key = (pkg_info["name"], pkg_info["type"], pkg_info["version"])
        if key in self._index:
            raise ValueError(f"Duplicate package: {pkg_info!r}")
        self._index.add(key)
        package = {
            "name": pkg_info["name"],
            "type": pkg_info["type"],
            "version": pkg_info["version"],
            "dependencies": deps,
        }
        if path != os.curdir:
            package["path"] = path
        self._packages.append(package)

    def write_to_file(self, file_name: Union[str, Path]) -> None:
        """Write the added packages to a file as JSON data.

        It ensures that the packages and every package's dependencies are sorted
        by the combination in the order of type, dev, name and version.

        :param file_name: an absolute or relative filename to write the added packages into.
            When a relative path is used, it will be opened directly and depends on the
            ``os.curdir``.
        :type file_name: str or pathlib.Path
        """
        self.sort()
        log.debug("Write packages with dependencies into file %s.", file_name)
        with open(file_name, "w", encoding="utf-8") as f:
            json.dump({"packages": self._packages}, f)

    def _clear_nfs_cache(self, file_name: Union[str, Path]) -> None:
        """
        Force the NFS to clear its cache by listing the directory's contents.

        This solution is intended for the specific use case of the application being deployed
        to a container environment that shares a single NFS volume. The NFS cache may cause
        issues for a second container reading the file right after it got written.

        :param file_name: an absolute or relative filename that contains the packages file.
        """
        dirname = os.path.dirname(file_name)

        if os.path.exists(dirname):
            log.info("Forcing the clearance of cache for %s directory", dirname)
            os.listdir(dirname)

    def load(self, file_name: Union[str, Path]) -> None:
        """Load data from a specified file written by write_to_file method.

        :param file_name: an absolute or relative filename to write the added packages into.
            When a relative path is used, it will be opened directly and depends on the
            ``os.curdir``. If the file does not exist, nothing is changed internally.
        :type file_name: str or pathlib.Path
        """
        self._clear_nfs_cache(file_name)

        if not os.path.exists(file_name):
            log.warning("Skipping the loading of non-existing file %s.", file_name)
            return

        with open(file_name, "r", encoding="utf-8") as f:
            data = json.load(f)
            packages = data.get("packages")
            if packages is None:
                log.warning("Packages data file %s does not include key 'packages'.", file_name)
                return

            log.info("Loaded file %s, found %i packages.", file_name, len(packages))

            for p in packages:
                self.add_package(p, p.get("path", os.curdir), p["dependencies"])

    def sort(self):
        """Sort both added packages and every package's dependencies in place.

        Sorting order: type -> dev -> name -> version.
        If a package has a "dependencies" list, the packages inside it will be sorted as well.
        """
        self._packages.sort(key=_package_sort_key)
        for package in self._packages:
            deps = package.get("dependencies")
            if deps:
                deps.sort(key=_package_sort_key)
