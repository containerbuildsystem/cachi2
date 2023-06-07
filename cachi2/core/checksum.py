import base64
import hashlib
import logging
from collections import defaultdict
from os import PathLike
from pathlib import Path
from typing import Iterable, NamedTuple, Optional, Union

from cachi2.core.errors import PackageRejected

log = logging.getLogger(__name__)


SUPPORTED_ALGORITHMS = hashlib.algorithms_guaranteed


class ChecksumInfo(NamedTuple):
    """A cryptographic algorithm and a hex-encoded checksum calculated by that algorithm."""

    algorithm: str
    hexdigest: str

    def to_sri(self) -> str:
        """Return the Subresource Integrity representation of this ChecksumInfo.

        https://developer.mozilla.org/en-US/docs/Web/Security/Subresource_Integrity

        Note: npm and yarn use this format in their lockfiles.
        """
        bytes_sha = bytes.fromhex(self.hexdigest)
        base64_sha = base64.b64encode(bytes_sha).decode("utf-8")
        return f"{self.algorithm}-{base64_sha}"

    @classmethod
    def from_sri(cls, sri: str) -> "ChecksumInfo":
        """Convert the input Subresource Integrity value to ChecksumInfo."""
        algorithm, checksum = sri.split("-", 1)
        return ChecksumInfo(algorithm, base64.b64decode(checksum).hex())


class _MismatchInfo(NamedTuple):
    algorithm: str
    maybe_digest: Optional[str]  # None == algorithm is not supported


def must_match_any_checksum(
    file_path: Union[str, PathLike[str]],
    expected_checksums: Iterable[ChecksumInfo],
    chunk_size: int = 10240,
) -> None:
    """Verify that the file matches at least one of the expected checksums.

    Note: any checksum algorithms not supported by python's hashlib will be skipped.

    If none of the checksums match, log all the mismatches and skipped algorithms at WARNING level,
    then raise an exception.

    :param file_path: path to the file to verify
    :param expected_checksums: all the possible checksums for this file
    :param chunk_size: when computing checksums, read the file in chunks of this size
    :raises PackageRejected: if none of the expected checksums matched the actual checksum
                             (for any of the supported algorithms)
    """
    filename = Path(file_path).name
    mismatches: list[_MismatchInfo] = []

    for algorithm, expected_digests in _group_by_algorithm(expected_checksums).items():
        if algorithm in SUPPORTED_ALGORITHMS:
            digest = _get_hexdigest(file_path, algorithm, chunk_size)
        else:
            digest = None

        if digest not in expected_digests:
            mismatches.append(_MismatchInfo(algorithm, digest))
        else:
            log.debug("%s: %s checksum matches: %s", filename, algorithm, digest)
            return

    _log_mismatches(filename, mismatches)
    raise PackageRejected(
        f"Failed to verify {filename} against any of the provided checksums.",
        solution=(
            "Please check if the expected checksums are correct.\n"
            "Caution is advised; if the checksum previously did match, "
            "someone may have tampered with the file!"
        ),
    )


def _group_by_algorithm(checksums: Iterable[ChecksumInfo]) -> dict[str, set[str]]:
    digests_by_algorithm = defaultdict(set)
    for algorithm, digest in checksums:
        digests_by_algorithm[algorithm].add(digest)
    return digests_by_algorithm


def _get_hexdigest(file_path: Union[str, PathLike[str]], algorithm: str, chunk_size: int) -> str:
    with open(file_path, "rb") as f:
        hasher = hashlib.new(algorithm)
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
        return hasher.hexdigest()


def _log_mismatches(filename: str, mismatches: list[_MismatchInfo]) -> None:
    for algorithm, digest in mismatches:
        if digest is not None:
            log.warning("%s: %s checksum does not match (got: %s)", filename, algorithm, digest)
        else:
            log.warning(
                "%s: %s checksum not supported (supported: %s)",
                filename,
                algorithm,
                ", ".join(sorted(SUPPORTED_ALGORITHMS)),
            )
