# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from tarfile import ExtractError, TarFile


def safe_extract(tar: TarFile, path: str = ".", *, numeric_owner: bool = False):
    """
    CVE-2007-4559 replacement for extract() or extractall().

    By using extract() or extractall() on a tarfile object without sanitizing input,
    a maliciously crafted .tar file could perform a directory path traversal attack.
    The patch essentially checks to see if all tarfile members will be
    extracted safely and throws an exception otherwise.

    :param tarfile tar: the tarfile to be extracted.
    :param str path: specifies a different directory to extract to.
    :param numeric_owner: if True, only the numbers for user/group names are used and not the names.
    :raise ExtractError: if there is a Traversal Path Attempt in the Tar File.
    """
    abs_path = Path(path).resolve()
    for member in tar.getmembers():

        member_path = Path(path).joinpath(member.name)
        abs_member_path = member_path.resolve()

        if not abs_member_path.is_relative_to(abs_path):
            raise ExtractError("Attempted Path Traversal in Tar File")

    tar.extractall(path, numeric_owner=numeric_owner)
