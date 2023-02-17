# SPDX-License-Identifier: GPL-3.0-or-later
import logging
from pathlib import Path

import tomli

from cachi2.core.checksum import ChecksumInfo, must_match_any_checksum
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, RequestOutput
from cachi2.core.package_managers.general import download_binary_file
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)

DEFAULT_LOCK_FILE = "Cargo.lock"
DEFAULT_METADATA_FILE = "Cargo.toml"


def fetch_cargo_source(request: Request) -> RequestOutput:
    """Resolve and fetch cargo dependencies for the given request."""
    components: list[Component] = []
    for package in request.cargo_packages:
        info = _resolve_cargo(
            request.source_dir / package.path,
            request.output_dir,
            package.lock_file,
            package.pkg_name,
            package.pkg_version,
        )
        components.append(Component.from_package_dict(info["package"]))

        for dependency in info["dependencies"]:
            components.append(Component.from_package_dict(dependency))

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=[],
        project_files=[],
    )


def _resolve_cargo(
    app_path: Path, output_dir: Path, lock_file=None, pkg_name=None, pkg_version=None
):
    """
    Resolve and fetch cargo dependencies for the given cargo application.
    """
    if pkg_name is None and pkg_version is None:
        pkg_name, pkg_version = _get_cargo_metadata(app_path)
    assert pkg_name and pkg_version, "INVALID PACKAGE"

    dependencies = []
    if not lock_file:
        lock_file = app_path / DEFAULT_LOCK_FILE

    cargo_lock_dict = tomli.load(lock_file.open("rb"))
    for dependency in cargo_lock_dict["package"]:
        # assuming packages w/o checksum/source are either sub-packages or the package
        # itself
        if {"checksum", "source"} <= dependency.keys():
            dependencies.append(dependency)

    dependencies = _download_cargo_dependencies(output_dir, dependencies)
    return {
        "package": {"name": pkg_name, "version": pkg_version, "type": "cargo"},
        "dependencies": dependencies,
        "lock_file": lock_file,
    }


def _get_cargo_metadata(package_dir: Path):
    metadata_file = package_dir / DEFAULT_METADATA_FILE
    metadata = tomli.load(metadata_file.open("rb"))
    return metadata["package"]["name"], metadata["package"]["version"]


def _download_cargo_dependencies(output_path: RootedPath, cargo_dependencies: list[dict]):
    downloads = []
    for dep in cargo_dependencies:
        checksum_info = ChecksumInfo(algorithm="sha256", hexdigest=dep["checksum"])
        dep_name = dep["name"]
        dep_version = dep["version"]
        download_path = Path(output_path.join_within_root(f"{dep_name}-{dep_version}.crate"))
        download_path.parent.mkdir(exist_ok=True)
        download_url = f"https://crates.io/api/v1/crates/{dep_name}/{dep_version}/download"
        download_binary_file(download_url, download_path)
        must_match_any_checksum(download_path, [checksum_info])
        downloads.append(
            {
                "package": dep_name,
                "name": dep_name,
                "version": dep_version,
                "path": download_path,
                "type": "cargo",
                "dev": False,
            }
        )
    return downloads
