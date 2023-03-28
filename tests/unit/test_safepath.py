import re
from pathlib import Path
from typing import Union

import pytest

from cachi2.core.safepath import NotSubpath, SafePath


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
        SafePath("foo")


def test_safepath_repr() -> None:
    assert repr(SafePath("/some/path")) == "SafePath('/some/path')"


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
    safepath = SafePath(test_path)

    with pytest.raises(NotSubpath, match=expect_err_msg(test_path, subpath_in_err_msg)):
        safepath.safe_join(*joinpath_args)


def test_sub_safepath(test_path: Path) -> None:
    safepath = SafePath(test_path)

    with pytest.raises(NotSubpath, match=expect_err_msg(test_path / "subpath", "..")):
        safepath.safe_join("subpath").safe_join("..")

    with pytest.raises(
        NotSubpath, match=expect_err_msg(test_path / "subpath", "symlink-to-parent")
    ):
        safepath.safe_join("subpath").safe_join("symlink-to-parent")


def test_safepath_allows_safe_join(test_path: Path) -> None:
    safepath = SafePath(test_path)

    assert safepath.safe_join("subpath/..").path == test_path
    assert safepath.safe_join("subpath", "..").path == test_path

    assert safepath.safe_join("subpath", "symlink-to-parent").path == test_path

    assert safepath.safe_join("subpath").path == test_path / "subpath"
