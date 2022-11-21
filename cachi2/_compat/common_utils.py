# SPDX-License-Identifier: GPL-3.0-or-later
import urllib


def get_repo_name(url):
    """Get the repo name from the URL."""
    parsed_url = urllib.parse.urlparse(url)
    repo = parsed_url.path.strip("/")
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return repo
