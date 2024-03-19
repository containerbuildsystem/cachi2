import asyncio
import hashlib
import logging
import os
from typing import Optional, Union

from pydantic import BaseModel, PositiveInt, ValidationError, validator

from cachi2.core.config import get_config
from cachi2.core.package_managers.general import async_download_files
from cachi2.core.package_managers.rpm.base import RpmsLock
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


class Package(BaseModel):
    repoid: str
    url: str
    checksum: Optional[str] = None
    size: Optional[int] = None


class Arch(BaseModel):
    arch: str
    packages: Optional[list[Package]] = []
    sources: Optional[list[Package]] = []

    @validator("sources", "packages")
    def validate_version(cls, v: list[Package]) -> list[Package]:
        if v is None:
            return []  # set default value
        return v


class Root(BaseModel):
    lockfileVersion: PositiveInt
    lockfileVendor: str
    arches: list[Arch]


# just a minimal set of fields to identify the format
class Header(BaseModel):
    lockfileVersion: PositiveInt
    lockfileVendor: str


class RedhatRpmsLock(RpmsLock):
    def match_format(self) -> bool:
        try:
            header = Header(**self._content)  # parse lockfile header with pydantic
        except ValidationError:
            return False
        # format specific match evaluation
        return header.lockfileVendor == "redhat" and header.lockfileVersion == 1

    def process_format(self) -> None:
        # parse the whole lockfile with pydantic
        self._lockfile = Root(**self._content)

    def download(self, output_dir: RootedPath) -> None:
        for arch in self._lockfile.arches:
            log.debug(f"Downloading files for '{arch.arch}' architecture.")
            # files per URL for downloading packages & sources
            files: dict[str, Union[str, os.PathLike[str]]] = {}
            for pkg in arch.packages:
                dest = output_dir.join_within_root(arch.arch, pkg.repoid, os.path.basename(pkg.url))
                files[pkg.url] = dest.path
                self._files_metadata[dest.path] = {
                    "package": True,
                    "url": pkg.url,
                    "size": pkg.size,
                    "checksum": pkg.checksum,
                }
                os.makedirs(os.path.dirname(dest.path), exist_ok=True)

            for pkg in arch.sources:
                dest = output_dir.join_within_root(
                    "sources", arch.arch, pkg.repoid, os.path.basename(pkg.url)
                )
                files[pkg.url] = dest.path
                self._files_metadata[dest.path] = {
                    "package": False,
                    "url": pkg.url,
                    "size": pkg.size,
                    "checksum": pkg.checksum,
                }
                os.makedirs(os.path.dirname(dest.path), exist_ok=True)

            asyncio.run(async_download_files(files, get_config().concurrency_limit))

    def verify_downloaded(self) -> None:
        log.debug("Verification of downloaded files has started.")
        # check file size and checksum of downloaded files
        for file_path, file_metadata in self._files_metadata.items():
            if file_metadata["size"] is not None:  # size is optional
                if os.path.getsize(file_path) != file_metadata["size"]:
                    log.warning(f"Unexpected file size of '{file_path}' != {file_metadata['size']}")
                    continue

            if file_metadata["checksum"] is not None:  # checksum is optional
                alg, digest = file_metadata["checksum"].split(":")
                method = getattr(hashlib, alg.lower(), None)
                if not method:
                    log.warning(f"Unsupported hashing algorithm '{alg}' for '{file_path}'")
                    continue
                h = method(usedforsecurity=False)
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        h.update(chunk)
                if digest != h.hexdigest():
                    log.warning(f"Unmatched checksum of '{file_path}' != '{digest}'")
