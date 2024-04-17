import asyncio
import hashlib
import logging
import shlex
from os import PathLike
from pathlib import Path
from typing import Any, Union
from urllib.parse import quote

import yaml
from pydantic import ValidationError

from cachi2.core.config import get_config
from cachi2.core.errors import PackageManagerError, PackageRejected
from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.models.sbom import Component, Property
from cachi2.core.package_managers.general import async_download_files
from cachi2.core.package_managers.rpm.redhat import RedhatRpmsLock
from cachi2.core.rooted_path import RootedPath
from cachi2.core.utils import run_cmd

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
            redhat_rpms_lock = RedhatRpmsLock.model_validate(yaml_content)
        except ValidationError as e:
            loc = e.errors()[0]["loc"]
            msg = e.errors()[0]["msg"]
            raise PackageManagerError(
                f"RPM lockfile '{DEFAULT_LOCKFILE_NAME}' format is not valid: '{loc}: {msg}'",
                solution=(
                    "Check the correct format and whether any keys are missing in the lockfile."
                ),
            )

        package_dir = output_dir.join_within_root(DEFAULT_PACKAGE_DIR)
        metadata = _download(redhat_rpms_lock, package_dir.path)
        _verify_downloaded(metadata)

        lockfile_relative_path = source_dir.subpath_from_root / DEFAULT_LOCKFILE_NAME
        return _generate_sbom_components(metadata, lockfile_relative_path)


def _download(lockfile: RedhatRpmsLock, output_dir: Path) -> dict[Path, Any]:
    """
    Download packages mentioned in the lockfile.

    Go through the parsed lockfile structure and find all RPM and SRPM files.
    Create a metadata structure indexed by destination path used
    for later verification (size, checksum) after download.
    Prepare a list of files to be downloaded, and then download files.
    """
    metadata = {}
    for arch in lockfile.arches:
        log.info(f"Downloading files for '{arch.arch}' architecture.")
        # files per URL for downloading packages & sources
        files: dict[str, Union[str, PathLike[str]]] = {}
        for pkg in arch.packages:
            repoid = lockfile.internal_repoid if pkg.repoid is None else pkg.repoid
            dest = output_dir.joinpath(arch.arch, repoid, Path(pkg.url).name)
            files[pkg.url] = str(dest)
            metadata[dest] = {
                "url": pkg.url,
                "size": pkg.size,
                "checksum": pkg.checksum,
            }
            Path.mkdir(dest.parent, parents=True, exist_ok=True)

        for pkg in arch.source:
            repoid = lockfile.internal_source_repoid if pkg.repoid is None else pkg.repoid
            dest = output_dir.joinpath(arch.arch, repoid, Path(pkg.url).name)
            files[pkg.url] = str(dest)
            metadata[dest] = {
                "url": pkg.url,
                "size": pkg.size,
                "checksum": pkg.checksum,
            }
            Path.mkdir(dest.parent, parents=True, exist_ok=True)

        asyncio.run(async_download_files(files, get_config().concurrency_limit))
    return metadata


def _verify_downloaded(metadata: dict[Path, Any]) -> None:
    """Use metadata structure with file sizes and checksums for verification \
    of downloaded packages and sources."""
    log.debug("Verification of downloaded files has started.")

    def raise_exception(message: str) -> None:
        raise PackageRejected(
            f"Some RPM packages or sources weren't verified after being downloaded: '{message}'",
            solution=(
                "Check the source of the data or check the corresponding metadata "
                "in the lockfile (size, checksum)."
            ),
        )

    # check file size and checksum of downloaded files
    for file_path, file_metadata in metadata.items():
        # size is optional
        if file_metadata["size"] is not None:
            if file_path.stat().st_size != file_metadata["size"]:
                raise_exception(f"Unexpected file size of '{file_path}' != {file_metadata['size']}")

        # checksum is optional
        if file_metadata["checksum"] is not None:
            alg, digest = file_metadata["checksum"].split(":")
            method = getattr(hashlib, alg.lower(), None)
            if method is not None:
                h = method(usedforsecurity=False)
            else:
                raise_exception(f"Unsupported hashing algorithm '{alg}' for '{file_path}'")
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(READ_CHUNK), b""):
                    h.update(chunk)
            if digest != h.hexdigest():
                raise_exception(f"Unmatched checksum of '{file_path}' != '{digest}'")


def _generate_sbom_components(
    files_metadata: dict[Path, Any], lockfile_path: Path
) -> list[Component]:
    """Fill the component list with the package records."""
    components: list[Component] = []
    for file_path, file_metadata in files_metadata.items():
        query_format = (
            # all nvra macros should be present/mandatory in RPM
            "%{NAME}\n"
            "%{VERSION}\n"
            "%{RELEASE}\n"
            "%{ARCH}\n"
            # vendor and epoch are optional in RPM file and in PURL as well
            # return "" when vendor is not set instead of "(None)"
            "%|VENDOR?{%{VENDOR}}:{}|\n"
            # return "" when epoch is not set instead of "(None)"
            "%|EPOCH?{%{EPOCH}}:{}|\n"
        )
        rpm_args = [
            "-q",
            "--queryformat",
            query_format.strip(),
            str(file_path),
        ]
        rpm_fields = run_cmd(cmd=["rpm", *rpm_args], params={})
        name, version, release, arch, vendor, epoch = rpm_fields.split("\n")
        log.debug(
            f"RPM attributes for '{file_path}': name='{name}', version='{version}', "
            f"release='{release}', arch='{arch}', vendor='{vendor}', epoch='{epoch}'"
        )

        # sanitize RPM attributes (including replacing whitespaces)
        vendor = quote(vendor.lower())
        download_url = quote(file_metadata["url"])

        # https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst#rpm
        # https://github.com/package-url/purl-spec/blob/master/PURL-SPECIFICATION.rst#known-qualifiers-keyvalue-pairsa
        purl = (
            f"pkg:rpm{'/' if vendor else ''}{vendor}/{name}@{version}-{release}"
            f"?arch={arch}{'&epoch=' if epoch else ''}{epoch}&download_url={download_url}"
        )

        if file_metadata["checksum"] is None:
            properties = [Property(name="cachi2:missing_hash:in_file", value=str(lockfile_path))]
        else:
            properties = []

        components.append(
            Component(
                name=name,
                version=version,
                purl=purl,
                properties=properties,
            )
        )
    return components


def inject_files_post(from_output_dir: Path, for_output_dir: Path, **kwargs: Any) -> None:
    """Run extra tasks for the RPM package manager (callback method) within `inject-files` cmd."""
    if Path.exists(from_output_dir.joinpath(DEFAULT_PACKAGE_DIR)):
        _generate_repos(from_output_dir)
        _generate_repofiles(from_output_dir, for_output_dir)


def _generate_repos(from_output_dir: Path) -> None:
    """Search structure for all repoid dirs and create repository metadata \
    out of its RPMs (and SRPMs)."""
    package_dir = from_output_dir.joinpath(DEFAULT_PACKAGE_DIR)
    for arch in package_dir.iterdir():
        if not arch.is_dir():
            continue
        for entry in arch.iterdir():
            if not entry.is_dir() or entry.name == "repos.d":
                continue
            repoid = entry.name
            _createrepo(repoid, entry)


def _createrepo(reponame: str, repodir: Path) -> None:
    """Execute the createrepo utility."""
    log.info(f"Creating repository metadata for repoid '{reponame}': {repodir}")
    cmd = ["createrepo_c", str(repodir)]
    log.debug("$ " + shlex.join(cmd))
    stdout = run_cmd(cmd, params={})
    log.debug(stdout)


def _generate_repofiles(from_output_dir: Path, for_output_dir: Path) -> None:
    """
    Generate templates of repofiles for all arches.

    Search structure at 'path' and generate one repofile content for each arch.
    Each repofile contains all arch's repoids (including repoids with source RPMs).
    Repofile (cachi2.repo) for particular arch will be stored in arch's dir in 'repos.d' subdir.
    Repofiles are not directly created from the templates in this method - templates are stored
    in the project file.
    """
    package_dir = from_output_dir.joinpath(DEFAULT_PACKAGE_DIR)
    for arch in package_dir.iterdir():
        if not arch.is_dir():
            continue
        log.debug(f"Preparing repofile content for arch '{arch.name}'")
        content = ""
        for entry in sorted(arch.iterdir()):
            if not entry.is_dir() or entry.name == "repos.d":
                continue
            repoid = entry.name
            localpath = for_output_dir.joinpath(DEFAULT_PACKAGE_DIR, arch.name, repoid)
            content += f"[{repoid}]\n"
            content += f"baseurl=file://{localpath}\n"
            content += "gpgcheck=1\n"
            # repoid directory matches the internal repoid
            if repoid.startswith("cachi2-"):
                content += "name=Packages unaffiliated with an official repository\n"

        if content:
            repo_file_path = arch.joinpath("repos.d", "cachi2.repo")
            if repo_file_path.exists():
                log.warning(f"Overwriting {repo_file_path}")
            else:
                Path.mkdir(arch.joinpath("repos.d"), parents=True, exist_ok=True)
                log.info(f"Creating {repo_file_path}")

            with open(repo_file_path, "w") as repo_file:
                repo_file.write(content)
