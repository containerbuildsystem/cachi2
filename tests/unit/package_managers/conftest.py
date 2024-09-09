from pathlib import Path

import git
import pytest

from cachi2.core.rooted_path import RootedPath


@pytest.fixture()
def rooted_tmp_path(tmp_path: Path) -> RootedPath:
    return RootedPath(tmp_path)


@pytest.fixture()
def rooted_tmp_path_repo(rooted_tmp_path: RootedPath) -> RootedPath:
    repo = git.Repo.init(rooted_tmp_path)
    repo.git.config("user.name", "user")
    repo.git.config("user.email", "user@example.com")

    Path(rooted_tmp_path, "README.md").touch()
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")

    return rooted_tmp_path
