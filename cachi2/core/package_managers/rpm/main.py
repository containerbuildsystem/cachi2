import asyncio
import hashlib
import logging
import shlex
from configparser import ConfigParser
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any, Dict, Optional, Union, no_type_check
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


@dataclass
class Package:
    """An RPM package with relevant data for the SBOM generation."""

    name: str
    version: str
    release: str
    arch: str
    epoch: str
    vendor: str
    download_url: str
    checksum: Optional[str] = None

    @classmethod
    def from_filepath(cls, rpm_filepath: Path, rpm_download_metadata: dict[str, str]) -> "Package":
        """Instantiate a package dataclass instance from a download RPM file path."""
        name, version, release, arch, vendor, epoch = cls._query_rpm_fields(rpm_filepath)
        return cls(
            name,
            version,
            release,
            arch,
            epoch,
            vendor,
            rpm_download_metadata["url"],
            rpm_download_metadata["checksum"],
        )

    @staticmethod
    def _query_rpm_fields(file_path: Path) -> list[str]:
        query_format = (
            # all nvra macros should be present/mandatory in RPM
            "%{NAME}\n"
            "%{VERSION}\n"
            "%{RELEASE}\n"
            "%{ARCH}\n"
            # vendor and epoch are optional RPM tags; return "" if not set instead of "(None)"
            "%|VENDOR?{%{VENDOR}}:{}|\n"
            "%|EPOCH?{%{EPOCH}}:{}|\n"
        )
        rpm_args = [
            "-q",
            "--queryformat",
            query_format.strip(),
            str(file_path),
        ]
        rpm_fields = run_cmd(cmd=["rpm", *rpm_args], params={})
        return rpm_fields.split("\n")

    @property
    def purl(self) -> str:
        """Get the purl for this package."""
        vendor = quote(self.vendor.lower())
        download_url = quote(self.download_url)

        # https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst#rpm
        # https://github.com/package-url/purl-spec/blob/master/PURL-SPECIFICATION.rst#known-qualifiers-keyvalue-pairsa
        purl = (
            f"pkg:rpm{'/' if self.vendor else ''}{vendor}/{self.name}@"
            f"{self.version}-{self.release}"
            f"?arch={self.arch}{'&epoch=' if self.epoch else ''}{self.epoch}"
            f"&download_url={download_url}"
        )
        return purl

    def to_component(self, lockfile_path: Path) -> Component:
        """Create an SBOM component for this package."""
        properties = []
        if not self.checksum:
            properties = [Property(name="cachi2:missing_hash:in_file", value=str(lockfile_path))]

        return Component(
            name=self.name, version=self.version, purl=self.purl, properties=properties
        )


class _Repofile(ConfigParser):
    def _apply_defaults(self) -> None:
        defaults = self.defaults()

        if not defaults:
            return

        # apply defaults per-section
        for s in self.sections():
            section = self[s]

            # ConfigParser's section is of the Mapping abstract type rather than a dictionary.
            # That means that when queried for options the results will include the defaults.
            # However, those defaults are referenced from a different map which on its own is good
            # until one tries to dump the ConfigParser instance to a file which will create a
            # dedicated section for the defaults -> [DEFAULTS] which we don't want.
            # This hackish line will make sure that by converting both the defaults and existing
            # section options to dictionaries and merging those back to the section object will
            # bake the defaults into each section rather than referencing them from a different
            # map, allowing us to rid of the defaults right before we dump the contents to a file
            section.update(dict(defaults) | dict(section))

        # defaults applied, clear the default section to prevent it from being formatted to the
        # output as
        #  [DEFAULTS]
        #  default1=val'
        self[self.default_section].clear()

    @property
    def empty(self) -> bool:
        return not bool(self.sections())

    # typeshed uses a private protocol type for the file-like object:
    # https://github.com/python/typeshed/blob/0445d74489d7a0b04a8c64a5a349ada1408718a9/stdlib/configparser.pyi#L197
    @no_type_check
    def write(self, fileobject, space_around_delimiters=True) -> None:
        self._apply_defaults()
        return super().write(fileobject, space_around_delimiters)


def fetch_rpm_source(request: Request) -> RequestOutput:
    """Process all the rpm source directories in a request."""
    components: list[Component] = []
    options: Dict[str, Any] = {}
    noptions = 0

    for package in request.rpm_packages:
        path = request.source_dir.join_within_root(package.path)
        components.extend(_resolve_rpm_project(path, request.output_dir))

        # FIXME: this is only ever good enough for a PoC, but needs to be handled properly in the
        # future.
        # It's unlikely that a project would be split into multiple packages, i.e. supplying
        # multiple rpms.lock.yaml files. We'd end up generating a single .repo file anyway,
        # however, although trying to pass conflicting options to DNF for identical repoids via the
        # input JSON doesn't make much sense from practical perspective (i.e. there's going to be a
        # single .repo file) the CLI technically allows it in the input JSON.
        # We're deliberately taking the easy route here by only assuming the "last" set of options
        # we found in the input JSON instead of doing a deep merge of all the nested dicts.
        # Nevertheless, we'll at least emit a warning at the end so that the user is informed
        if package.options and package.options.dnf:
            options = package.options.model_dump()
            noptions += 1

    if noptions > 1:
        log.warning(
            "Multiple sets of DNF options detected on the input: "
            "Only one input RPM project package can specify extra DNF options, "
            "the last one seen will take effect"
        )

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=[],
        project_files=[],
        options={"rpm": options} if options else None,
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
            repoid = lockfile.cachi2_repoid if pkg.repoid is None else pkg.repoid
            dest = output_dir.joinpath(arch.arch, repoid, Path(pkg.url).name)
            files[pkg.url] = str(dest)
            metadata[dest] = {
                "url": pkg.url,
                "size": pkg.size,
                "checksum": pkg.checksum,
            }
            Path.mkdir(dest.parent, parents=True, exist_ok=True)

        for pkg in arch.source:
            repoid = lockfile.cachi2_source_repoid if pkg.repoid is None else pkg.repoid
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
    components = []
    for file_path, file_metadata in files_metadata.items():
        package = Package.from_filepath(file_path, file_metadata)
        components.append(package.to_component(lockfile_path))
    return components


def inject_files_post(from_output_dir: Path, for_output_dir: Path, **kwargs: Any) -> None:
    """Run extra tasks for the RPM package manager (callback method) within `inject-files` cmd."""
    if Path.exists(from_output_dir.joinpath(DEFAULT_PACKAGE_DIR)):
        _generate_repos(from_output_dir)
        _generate_repofiles(from_output_dir, for_output_dir, kwargs.get("options"))


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


def _generate_repofiles(
    from_output_dir: Path, for_output_dir: Path, options: Optional[Dict] = None
) -> None:
    """
    Generate templates of repofiles for all arches.

    Search structure at 'path' and generate one repofile content for each arch.
    Each repofile contains all arch's repoids (including repoids with source RPMs).
    Repofile (cachi2.repo) for particular arch will be stored in arch's dir in 'repos.d' subdir.
    Repofiles are not directly created from the templates in this method - templates are stored
    in the project file.
    """
    dnf_options = None
    dnf_options_repos = None

    if options:
        dnf_options = options.get("rpm", {}).get("dnf", {})
        dnf_options_repos = dnf_options.keys()

    package_dir = from_output_dir.joinpath(DEFAULT_PACKAGE_DIR)
    for arch in package_dir.iterdir():
        if not arch.is_dir():
            continue
        log.debug(f"Preparing repofile content for arch '{arch.name}'")
        repofile = _Repofile(defaults={"gpgcheck": "1"})

        for entry in arch.iterdir():
            if not entry.is_dir() or entry.name == "repos.d":
                continue
            repoid = entry.name
            repofile[repoid] = {}

            # TODO: purposefully ignoring the fact that options might be passed within the "main"
            # context of DNF options which would mean we'd have to generate a dnf.conf since such
            # options are global, skipping that for now
            if dnf_options and dnf_options_repos and repoid in dnf_options_repos:
                repofile[repoid] = dnf_options[repoid]

            localpath = for_output_dir.joinpath(DEFAULT_PACKAGE_DIR, arch.name, repoid)
            repofile[repoid]["baseurl"] = f"file://{localpath}"

            # repoid directory matches the internal repoid
            if repoid.startswith("cachi2-"):
                repofile[repoid]["name"] = "Packages unaffiliated with an official repository"

        if not repofile.empty:
            repo_file_path = arch.joinpath("repos.d", "cachi2.repo")
            if repo_file_path.exists():
                log.warning(f"Overwriting {repo_file_path}")
            else:
                Path.mkdir(arch.joinpath("repos.d"), parents=True, exist_ok=True)
                log.info(f"Creating {repo_file_path}")

            with open(repo_file_path, "w") as f:
                repofile.write(f)
