# SPDX-License-Identifier: GPL-3.0-or-later
import collections
import hashlib
import os
import urllib

import requests

from cachi2.core.errors import FetchError, PackageRejected
from cachi2.core.http_requests import SAFE_REQUEST_METHODS, get_requests_session

__all__ = [
    "verify_checksum",
    "ChecksumInfo",
]

ChecksumInfo = collections.namedtuple("ChecksumInfo", "algorithm hexdigest")

pkg_requests_session = get_requests_session(retry_options={"allowed_methods": SAFE_REQUEST_METHODS})


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


def download_binary_file(url, download_path, auth=None, insecure=False, chunk_size=8192):
    """
    Download a binary file (such as a TAR archive) from a URL.

    :param str url: URL for file download
    :param (str | Path) download_path: Path to download file to
    :param requests.auth.AuthBase auth: Authentication for the URL
    :param bool insecure: Do not verify SSL for the URL
    :param int chunk_size: Chunk size param for Response.iter_content()
    :raise FetchError: If download failed
    """
    try:
        resp = pkg_requests_session.get(url, stream=True, verify=not insecure, auth=auth)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise FetchError(f"Could not download {url}: {e}")

    with open(download_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            f.write(chunk)


def extract_git_info(vcs_url):
    """
    Extract important info from a VCS requirement URL.

    Given a URL such as git+https://user:pass@host:port/namespace/repo.git@123456?foo=bar#egg=spam
    this function will extract:
    - the "clean" URL: https://user:pass@host:port/namespace/repo.git
    - the git ref: 123456
    - the host, namespace and repo: host:port, namespace, repo

    The clean URL and ref can be passed straight to scm.Git to fetch the repo.
    The host, namespace and repo will be used to construct the file path under deps/pip.

    :param str vcs_url: The URL of a VCS requirement, must be valid (have git ref in path)
    :return: Dict with url, ref, host, namespace and repo keys
    """
    # If scheme is git+protocol://, keep only protocol://
    # Do this before parsing URL, otherwise urllib may not extract URL params
    if vcs_url.startswith("git+"):
        vcs_url = vcs_url[len("git+") :]

    url = urllib.parse.urlparse(vcs_url)

    ref = url.path[-40:]  # Take the last 40 characters (the git ref)
    clean_path = url.path[:-41]  # Drop the last 41 characters ('@' + git ref)

    # Note: despite starting with an underscore, the namedtuple._replace() method is public
    clean_url = url._replace(path=clean_path, params="", query="", fragment="")

    # Assume everything up to the last '@' is user:pass. This should be kept in the
    # clean URL used for fetching, but should not be considered part of the host.
    _, _, clean_netloc = url.netloc.rpartition("@")

    namespace_repo = clean_path.strip("/")
    if namespace_repo.endswith(".git"):
        namespace_repo = namespace_repo[: -len(".git")]

    # Everything up to the last '/' is namespace, the rest is repo
    namespace, _, repo = namespace_repo.rpartition("/")

    return {
        "url": clean_url.geturl(),
        "ref": ref.lower(),
        "host": clean_netloc,
        "namespace": namespace,
        "repo": repo,
    }
