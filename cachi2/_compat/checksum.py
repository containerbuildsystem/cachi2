# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib
from pathlib import Path
from typing import Union

from cachi2._compat.errors import UnknownHashAlgorithm


def hash_file(file_path: Union[str, Path], chunk_size: int = 10240, algorithm: str = "sha256"):
    """Hash a file.

    :param file_path: compute checksum for this file.
    :type file_path: str, pathlib.Path
    :param int chunk_size: the optional chunk size passed to file object ``read`` method.
    :param str algorithm: the algorithm name used to hash the file. By default, sha256 is used.
    :return: a hash object containing the data to generate digest.
    :rtype: Hasher
    :raise UnknownHashAlgorithm: if the algorithm cannot be found.
    """
    try:
        hasher = hashlib.new(algorithm)
    except ValueError:
        raise UnknownHashAlgorithm(f"Hash algorithm {algorithm} is unknown.")
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher
