import re
from pathlib import Path
from typing import Union

import pytest

from cachi2.core.safepath import NotSubpath, RootedPath


@pytest.fixture
def test_path(tmp_path: Path) -> Path:
    tmp_path.joinpath("symlink-to-parent").symlink_to("..")
    tmp_path.joinpath("subpath").mkdir()
    tmp_path.joinpath("subpath/symlink-to-parent").symlink_to("..")
    tmp_path.joinpath("subpath/symlink-to-abspath").symlink_to("/abspath")
    return tmp_path


def expect_err_msg(parent: Union[str, Path], subpath: Union[str, Path]) -> str:
    return re.escape(
        f"supposed subpath ({Path(subpath)}) leads outside parent path ({Path(parent)})"
    )


def test_safepath_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="path must be absolute: foo"):
        RootedPath("foo")


def test_safepath_repr() -> None:
    assert repr(RootedPath("/some/path")) == "SafePath('/some/path')"


@pytest.mark.parametrize(
    "joinpath_args, subpath_in_err_msg",
    [
        ([".."], ".."),
        (["/abspath"], "/abspath"),
        (["subpath/../.."], "subpath/../.."),
        (["subpath", "..", ".."], "subpath/../.."),
        (["subpath", "..", "/abspath"], "/abspath"),
        (["symlink-to-parent"], "symlink-to-parent"),
        (["subpath/symlink-to-abspath"], "subpath/symlink-to-abspath"),
        (["subpath", "symlink-to-abspath"], "subpath/symlink-to-abspath"),
    ],
)
def test_safepath_rejects_unsafe_joinpath(
    joinpath_args: list[str], subpath_in_err_msg: str, test_path: Path
) -> None:
    safepath = RootedPath(test_path)

    with pytest.raises(NotSubpath, match=expect_err_msg(test_path, subpath_in_err_msg)):
        safepath.join_within_root(*joinpath_args)


def test_sub_safepath(test_path: Path) -> None:
    safepath = RootedPath(test_path)

    with pytest.raises(NotSubpath, match=expect_err_msg(test_path / "subpath", "..")):
        safepath.join_within_root("subpath").join_within_root("..")

    with pytest.raises(
        NotSubpath, match=expect_err_msg(test_path / "subpath", "symlink-to-parent")
    ):
        safepath.join_within_root("subpath").join_within_root("symlink-to-parent")


def test_safepath_allows_safe_join(test_path: Path) -> None:
    safepath = RootedPath(test_path)

    assert safepath.join_within_root("subpath/..").path == test_path
    assert safepath.join_within_root("subpath", "..").path == test_path

    assert safepath.join_within_root("subpath", "symlink-to-parent").path == test_path

    assert safepath.join_within_root("subpath").path == test_path / "subpath"
