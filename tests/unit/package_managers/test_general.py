# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from typing import Any, Optional
from unittest import mock

import pytest
import requests
from requests.auth import AuthBase, HTTPBasicAuth

from cachi2.core.config import get_config
from cachi2.core.errors import FetchError
from cachi2.core.package_managers import general
from cachi2.core.package_managers.general import download_binary_file, pkg_requests_session

GIT_REF = "9a557920b2a6d4110f838506120904a6fda421a2"


@pytest.mark.parametrize("auth", [None, HTTPBasicAuth("user", "password")])
@pytest.mark.parametrize("insecure", [True, False])
@pytest.mark.parametrize("chunk_size", [1024, 2048])
@mock.patch.object(pkg_requests_session, "get")
def test_download_binary_file(
    mock_get: Any, auth: Optional[AuthBase], insecure: bool, chunk_size: int, tmp_path: Path
) -> None:
    timeout = get_config().requests_timeout
    url = "http://example.org/example.tar.gz"
    content = b"file content"

    mock_response = mock_get.return_value
    mock_response.iter_content.return_value = [content]

    download_path = tmp_path.joinpath("example.tar.gz")
    download_binary_file(
        url, str(download_path), auth=auth, insecure=insecure, chunk_size=chunk_size
    )

    assert download_path.read_bytes() == content
    mock_get.assert_called_with(url, stream=True, verify=not insecure, auth=auth, timeout=timeout)
    mock_response.iter_content.assert_called_with(chunk_size=chunk_size)


@mock.patch.object(pkg_requests_session, "get")
def test_download_binary_file_failed(mock_get: Any) -> None:
    mock_get.side_effect = [requests.RequestException("Something went wrong")]

    expected = "Could not download http://example.org/example.tar.gz: Something went wrong"
    with pytest.raises(FetchError, match=expected):
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
def test_extract_git_info(url: str, nonstandard_info: Any) -> None:
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
