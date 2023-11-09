# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from textwrap import dedent
from typing import Any
import hashlib
import json
import logging
import tarfile
import urllib

from packageurl import PackageURL
import tomli

from cachi2.core.checksum import ChecksumInfo, must_match_any_checksum
from cachi2.core.models.input import CargoPackageInput, Request
from cachi2.core.models.output import Component, ProjectFile, RequestOutput
from cachi2.core.package_managers.general import download_binary_file
from cachi2.core.rooted_path import RootedPath
from cachi2.core.scm import get_repo_id

log = logging.getLogger(__name__)

DEFAULT_LOCK_FILE = "Cargo.lock"
DEFAULT_METADATA_FILE = "Cargo.toml"


def fetch_cargo_source(request: Request) -> RequestOutput:
    """Resolve and fetch cargo dependencies for the given request."""
    components: list[Component] = []
    for package in request.cargo_packages:
        info = _resolve_cargo(request.source_dir, request.output_dir, package)
        components.append(Component.from_package_dict(info["package"]))
        for dependency in info["dependencies"]:
            dep_purl = _generate_purl_dependency(dependency)
            components.append(
                Component(
                    name=dependency["name"],
                    version=dependency["version"],
                    purl=dep_purl,
                )
            )

    cargo_config = ProjectFile(
        abspath=Path(request.source_dir.join_within_root(".cargo/config.toml")),
        template=dedent(
            """
            [source.crates-io]
            replace-with = "local"

            [source.local]
            directory = "${output_dir}/deps/cargo"
            """
        ),
    )

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=[],
        project_files=[cargo_config],
    )


def _resolve_cargo(source_dir: Path, output_dir: Path, package: CargoPackageInput):
    """
    Resolve and fetch cargo dependencies for the given cargo application.
    """
    app_path = source_dir / package.path
    pkg_name = package.pkg_name
    pkg_version = package.pkg_version
    if pkg_name is None and pkg_version is None:
        pkg_name, pkg_version = _get_cargo_metadata(app_path)
    assert pkg_name and pkg_version, "INVALID PACKAGE"

    purl = _generate_purl_main_package(pkg_name, pkg_version, source_dir)

    dependencies = []
    lock_file = app_path / (package.lock_file or DEFAULT_LOCK_FILE)

    cargo_lock_dict = tomli.load(lock_file.open("rb"))
    for dependency in cargo_lock_dict["package"]:
        # assuming packages w/o checksum/source are either sub-packages or the package
        # itself
        if {"checksum", "source"} <= dependency.keys():
            dependencies.append(dependency)

    dependencies = _download_cargo_dependencies(output_dir, dependencies)
    return {
        "package": {"name": pkg_name, "version": pkg_version, "type": "cargo", "purl": purl},
        "dependencies": dependencies,
        "lock_file": lock_file,
    }


def _get_cargo_metadata(package_dir: Path):
    metadata_file = package_dir / DEFAULT_METADATA_FILE
    metadata = tomli.load(metadata_file.open("rb"))
    return metadata["package"]["name"], metadata["package"]["version"]


def _download_cargo_dependencies(
    output_path: RootedPath, cargo_dependencies: list[dict]
) -> list[dict[str, Any]]:
    downloads = []
    for dep in cargo_dependencies:
        checksum_info = ChecksumInfo(algorithm="sha256", hexdigest=dep["checksum"])
        dep_name = dep["name"]
        dep_version = dep["version"]
        download_path = Path(
            output_path.join_within_root(f"deps/cargo/{dep_name}-{dep_version}.crate")
        )
        download_path.parent.mkdir(exist_ok=True, parents=True)
        download_url = f"https://crates.io/api/v1/crates/{dep_name}/{dep_version}/download"
        download_binary_file(download_url, download_path)
        must_match_any_checksum(download_path, [checksum_info])
        vendored_dep = prepare_crate_as_vendored_dep(download_path)
        downloads.append(
            {
                "package": dep_name,
                "name": dep_name,
                "version": dep_version,
                "path": vendored_dep,
                "type": "cargo",
                "dev": False,
                "kind": "cratesio",
            }
        )
    return downloads


def _calc_sha256(content: bytes):
    return hashlib.sha256(content).hexdigest()


def generate_cargo_checksum(crate_path: Path):
    """Generate Cargo checksums

    cargo requires vendored dependencies to have a ".cargo_checksum.json" BUT crates
    downloaded from crates.io don't come with this file. This function generates
    a dictionary compatible what cargo expects.

    Args:
        crate_path (Path): crate tarball

    Returns:
        dict: checksums expected by cargo
    """
    checksums = {"package": _calc_sha256(crate_path.read_bytes()), "files": {}}
    tarball = tarfile.open(crate_path)
    for tarmember in tarball.getmembers():
        name = tarmember.name.split("/", 1)[1]  # ignore folder name
        checksums["files"][name] = _calc_sha256(tarball.extractfile(tarmember.name).read())
    tarball.close()
    return checksums


def prepare_crate_as_vendored_dep(crate_path: Path) -> Path:
    """Prepare crates as vendored dependencies

    Extracts contents from crate and add a ".cargo_checksum.json" file to it

    Args:
        crate_path (Path): crate tarball
    """
    checksums = generate_cargo_checksum(crate_path)
    with tarfile.open(crate_path) as tarball:
        folder_name = tarball.getnames()[0].split("/")[0]
        tarball.extractall(crate_path.parent)
    cargo_checksum = crate_path.parent / folder_name / ".cargo-checksum.json"
    json.dump(checksums, cargo_checksum.open("w"))
    return crate_path.parent / folder_name


def _generate_purl_main_package(name: str, version: str, package_path: RootedPath) -> str:
    """Get the purl for this package."""
    type = "cargo"
    url = get_repo_id(package_path.root).as_vcs_url_qualifier()
    qualifiers = {"vcs_url": url}
    if package_path.subpath_from_root != Path("."):
        subpath = package_path.subpath_from_root.as_posix()
    else:
        subpath = None

    purl = PackageURL(
        type=type,
        name=name,
        version=version,
        qualifiers=qualifiers,
        subpath=subpath,
    )

    return purl.to_string()


def _generate_purl_dependency(package: dict[str, Any]) -> str:
    """Get the purl for this dependency."""
    type = "cargo"
    name = package["name"]
    dependency_kind = package.get("kind", None)
    version = None
    qualifiers = None

    if dependency_kind == "cratesio":
        version = package["version"]
    elif dependency_kind == "vcs":
        qualifiers = {"vcs_url": package["version"]}
    elif dependency_kind == "url":
        parsed_url = urllib.parse.urldefrag(package["version"])
        fragments = urllib.parse.parse_qs(parsed_url.fragment)
        checksum = fragments["cachito_hash"][0]
        qualifiers = {"download_url": parsed_url.url, "checksum": checksum}
    else:
        # Should not happen
        raise RuntimeError(f"Unexpected requirement kind: {dependency_kind}")

    purl = PackageURL(
        type=type,
        name=name,
        version=version,
        qualifiers=qualifiers,
    )

    return purl.to_string()
