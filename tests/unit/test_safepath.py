import re
from pathlib import Path
from typing import Union

import pytest

from cachi2.core.safepath import NotSubpath, SafePath


def test_safepath_stays_safe() -> None:
    safepath = SafePath("/foo")
    assert isinstance(safepath / "bar", SafePath)
    assert isinstance(safepath.joinpath("bar"), SafePath)


def test_safepath_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="safe path must be absolute but isn't: foo"):
        SafePath("foo")


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

    with pytest.raises(NotSubpath, match=expect_err_msg(safepath, subpath_in_err_msg)):
        safepath.joinpath(*joinpath_args)


def test_safepath_rejects_unsafe_join_operator(test_path: Path) -> None:
    safepath = SafePath(test_path)

    with pytest.raises(NotSubpath, match=expect_err_msg(safepath, "..")):
        _ = safepath / ".."

    with pytest.raises(NotSubpath, match=expect_err_msg(safepath, "symlink-to-parent")):
        _ = safepath / "symlink-to-parent"

    with pytest.raises(NotSubpath, match=expect_err_msg(safepath / "subpath", "..")):
        _ = safepath / "subpath" / ".."

    with pytest.raises(NotSubpath, match=expect_err_msg(safepath / "subpath", "symlink-to-parent")):
        _ = safepath / "subpath" / "symlink-to-parent"


def test_safepath_allows_safe_join(test_path: Path) -> None:
    safepath = SafePath(test_path)

    assert safepath / "subpath/.." == safepath
    assert safepath.joinpath("subpath", "..") == safepath

    assert safepath / "subpath/symlink-to-parent" == safepath
    assert safepath.joinpath("subpath", "symlink-to-parent") == safepath

    assert safepath / "subpath" == test_path / "subpath"
    assert safepath.joinpath("subpath") == test_path / "subpath"
