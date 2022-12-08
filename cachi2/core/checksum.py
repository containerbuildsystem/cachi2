import hashlib
import os
from typing import NamedTuple

from cachi2.core.errors import PackageRejected


class ChecksumInfo(NamedTuple):
    """A cryptographic algorithm and a hex-encoded checksum calculated by that algorithm."""

    algorithm: str
    hexdigest: str


def verify_checksum(file_path: str, checksum_info: ChecksumInfo, chunk_size: int = 10240):
    """
    Verify the checksum of the file at the given path matches the expected checksum info.

    :param str file_path: the path to the file to be verified
    :param ChecksumInfo checksum_info: the expected checksum information
    :param int chunk_size: the amount of bytes to read at a time
    :raise PackageRejected: if the checksum is not as expected or cannot be computed
    """
    filename = os.path.basename(file_path)

    try:
        hasher = hashlib.new(checksum_info.algorithm)
    except ValueError:
        known_algorithms = sorted(hashlib.algorithms_guaranteed)
        msg = (
            f"Cannot perform checksum on the file {filename}, "
            f"unknown algorithm: {checksum_info.algorithm}. Known: {', '.join(known_algorithms)}"
        )
        raise PackageRejected(msg, solution="Please use one of the known hash algorithms.")

    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)

    computed_hexdigest = hasher.hexdigest()

    if computed_hexdigest != checksum_info.hexdigest:
        msg = (
            f"The file {filename} has an unexpected checksum value, "
            f"expected {checksum_info.hexdigest} but computed {computed_hexdigest}"
        )
        raise PackageRejected(
            msg,
            solution=(
                "Please verify that the specified hash is correct.\n"
                "Caution is advised; if the hash was previously correct, it means the content "
                "has changed!"
            ),
        )
