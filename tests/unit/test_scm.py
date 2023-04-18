import filecmp
import tarfile
from pathlib import Path

import pytest
from git.repo import Repo

from cachi2.core.errors import FetchError
from cachi2.core.scm import clone_as_tarball

INITIAL_COMMIT = "78510c591e2be635b010a52a7048b562bad855a3"


def test_clone_as_tarball(golang_repo_path: Path, tmp_path: Path) -> None:
    original_path = golang_repo_path
    to_path = tmp_path / "my-repo.tar.gz"

    clone_as_tarball(f"file://{original_path}", INITIAL_COMMIT, to_path)

    with tarfile.open(to_path) as tar:
        tar.extractall(tmp_path / "my-repo")

    my_path = tmp_path / "my-repo" / "app"

    original_repo = Repo(original_path)
    my_repo = Repo(my_path)

    assert original_repo.commit().hexsha != my_repo.commit().hexsha
    assert my_repo.commit().hexsha == INITIAL_COMMIT

    compare = filecmp.dircmp(original_path, my_path)
    assert compare.same_files == [
        ".gitignore",
        "README.md",
        "go.sum",
        "main.go",
    ]
    # go.mod is the only file that changed between the initial commit and the current one
    assert compare.diff_files == ["go.mod"]


def test_clone_as_tarball_wrong_url(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="Failed cloning the Git repository"):
        clone_as_tarball("file:///no/such/directory", INITIAL_COMMIT, tmp_path / "my-repo.tar.gz")


def test_clone_as_tarball_wrong_ref(golang_repo_path: Path, tmp_path: Path) -> None:
    bad_commit = "baaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaad"
    with pytest.raises(
        FetchError,
        match=f'Please verify the supplied reference of "{bad_commit}" is valid',
    ):
        clone_as_tarball(f"file://{golang_repo_path}", bad_commit, tmp_path / "my-repo.tar.gz")
