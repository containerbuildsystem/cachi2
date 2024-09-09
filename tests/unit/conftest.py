import tarfile
from pathlib import Path

import git
import pytest

from cachi2.core.rooted_path import RootedPath


@pytest.fixture
def data_dir() -> Path:
    """Path to the directory for storing unit test data."""
    return Path(__file__).parent / "data"


@pytest.fixture
def golang_repo_path(data_dir: Path, tmp_path: Path) -> Path:
    """Extract the golang git repo tarball to a tmpdir, return the path to the repo."""
    with tarfile.open(data_dir / "golang_git_repo.tar.gz") as tar:
        tar.extractall(tmp_path)

    return tmp_path / "golang_git_repo"


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
