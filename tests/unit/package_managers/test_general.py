# SPDX-License-Identifier: GPL-3.0-or-later
from unittest import mock

import pytest
import requests

from cachi2._compat.errors import InvalidChecksum, NetworkError
from cachi2.core.package_managers import general
from cachi2.core.package_managers.general import (
    ChecksumInfo,
    download_binary_file,
    pkg_requests_session,
    verify_checksum,
)

GIT_REF = "9a557920b2a6d4110f838506120904a6fda421a2"


def test_verify_checksum(tmpdir):
    file = tmpdir.join("spells.txt")
    file.write("Beetlejuice! Beetlejuice! Beetlejuice!")

    expected = {
        "sha512": (
            "da518fe8b800b3325fe35ca680085fe37626414d0916937a01a25ef8f5d7aa769b7233073235fce85ee"
            "c717e02bb9d72062656cf2d79223792a784910c267b54"
        ),
        "sha256": "ed1f8cd69bfacf0528744b6a7084f36e8841b6128de0217503e215612a0ee835",
        "md5": "308764bc995153f7d853827a675e6731",
    }
    for algorithm, checksum in expected.items():
        verify_checksum(str(file), ChecksumInfo(algorithm, checksum))


def test_verify_checksum_invalid_hexdigest(tmpdir):
    file = tmpdir.join("spells.txt")
    file.write("Beetlejuice! Beetlejuice! Beetlejuice!")

    expected_error = "The file spells.txt has an unexpected checksum value"
    with pytest.raises(InvalidChecksum, match=expected_error):
        verify_checksum(str(file), ChecksumInfo("sha512", "spam"))


def test_verify_checksum_unsupported_algorithm(tmpdir):
    file = tmpdir.join("spells.txt")
    file.write("Beetlejuice! Beetlejuice! Beetlejuice!")

    expected_error = "Cannot perform checksum on the file spells.txt,.*bacon.*"
    with pytest.raises(InvalidChecksum, match=expected_error):
        verify_checksum(str(file), ChecksumInfo("bacon", "spam"))


@pytest.mark.parametrize("auth", [None, ("user", "password")])
@pytest.mark.parametrize("insecure", [True, False])
@pytest.mark.parametrize("chunk_size", [1024, 2048])
@mock.patch.object(pkg_requests_session, "get")
def test_download_binary_file(mock_get, auth, insecure, chunk_size, tmpdir):
    url = "http://example.org/example.tar.gz"
    content = b"file content"

    mock_response = mock_get.return_value
    mock_response.iter_content.return_value = [content]

    download_path = tmpdir.join("example.tar.gz")
    download_binary_file(
        url, download_path.strpath, auth=auth, insecure=insecure, chunk_size=chunk_size
    )

    assert download_path.read_binary() == content
    mock_get.assert_called_with(url, stream=True, auth=auth, verify=not insecure)
    mock_response.iter_content.assert_called_with(chunk_size=chunk_size)


@mock.patch.object(pkg_requests_session, "get")
def test_download_binary_file_failed(mock_get):
    mock_get.side_effect = [requests.RequestException("Something went wrong")]

    expected = "Could not download http://example.org/example.tar.gz: Something went wrong"
    with pytest.raises(NetworkError, match=expected):
        download_binary_file("http://example.org/example.tar.gz", "/example.tar.gz")


@pytest.mark.parametrize(
    "url, nonstandard_info",  # See body of function for what is standard info
    [
        (
            # Standard case
            f"git+https://github.com/monty/python@{GIT_REF}",
            None,
        ),
        (
            # Ref should be converted to lowercase
            f"git+https://github.com/monty/python@{GIT_REF.upper()}",
            {"ref": GIT_REF},  # Standard but be explicit about it
        ),
        (
            # Repo ends with .git (that is okay)
            f"git+https://github.com/monty/python.git@{GIT_REF}",
            {"url": "https://github.com/monty/python.git"},
        ),
        (
            # git://
            f"git://github.com/monty/python@{GIT_REF}",
            {"url": "git://github.com/monty/python"},
        ),
        (
            # git+git://
            f"git+git://github.com/monty/python@{GIT_REF}",
            {"url": "git://github.com/monty/python"},
        ),
        (
            # No namespace
            f"git+https://github.com/python@{GIT_REF}",
            {"url": "https://github.com/python", "namespace": ""},
        ),
        (
            # Namespace with more parts
            f"git+https://github.com/monty/python/and/the/holy/grail@{GIT_REF}",
            {
                "url": "https://github.com/monty/python/and/the/holy/grail",
                "namespace": "monty/python/and/the/holy",
                "repo": "grail",
            },
        ),
        (
            # Port should be part of host
            f"git+https://github.com:443/monty/python@{GIT_REF}",
            {"url": "https://github.com:443/monty/python", "host": "github.com:443"},
        ),
        (
            # Authentication should not be part of host
            f"git+https://user:password@github.com/monty/python@{GIT_REF}",
            {
                "url": "https://user:password@github.com/monty/python",
                "host": "github.com",  # Standard but be explicit about it
            },
        ),
        (
            # Params, query and fragment should be stripped
            f"git+https://github.com/monty/python@{GIT_REF};foo=bar?bar=baz#egg=spam",
            {
                # Standard but be explicit about it
                "url": "https://github.com/monty/python",
            },
        ),
        (
            # RubyGems case
            f"https://github.com/monty/python@{GIT_REF}",
            {
                # Standard but be explicit about it
                "url": "https://github.com/monty/python",
            },
        ),
    ],
)
def test_extract_git_info(url, nonstandard_info):
    """Test extraction of git info from VCS URL."""
    info = {
        "url": "https://github.com/monty/python",
        "ref": GIT_REF,
        "namespace": "monty",
        "repo": "python",
        "host": "github.com",
    }
    info.update(nonstandard_info or {})
    assert general.extract_git_info(url) == info
