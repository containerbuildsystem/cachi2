from pathlib import Path
from typing import ContextManager, Literal

import pydantic
import pytest

from cachi2.core.rooted_path import PathOutsideRoot, RootedPath


@pytest.fixture
def test_path(tmp_path: Path) -> Path:
    tmp_path.joinpath("symlink-to-parent").symlink_to("..")
    tmp_path.joinpath("subpath").mkdir()
    tmp_path.joinpath("subpath/symlink-to-parent").symlink_to("..")
    tmp_path.joinpath("subpath/symlink-to-abspath").symlink_to("/abspath")
    return tmp_path


def assert_attrs(rooted_path: RootedPath, *, path: Path, root: Path) -> None:
    assert rooted_path.path == path
    assert rooted_path.root == root


def expect_path_outside_root(
    subpath: str, path: Path, root: Path
) -> ContextManager[pytest.ExceptionInfo[PathOutsideRoot]]:
    pattern = f"Joining path {subpath!r} to {str(path)!r}: target is outside {str(root)!r}"
    return pytest.raises(PathOutsideRoot, match=pattern)


def test_path_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="path must be absolute: foo"):
        RootedPath("foo")


def test_rooted_path_init() -> None:
    rooted_path = RootedPath("/some/directory")
    assert_attrs(rooted_path, path=Path("/some/directory"), root=Path("/some/directory"))


def test_join_within_root(test_path: Path) -> None:
    rooted_path = RootedPath(test_path)

    assert_attrs(
        rooted_path.join_within_root("nonexistent-subpath"),
        path=test_path / "nonexistent-subpath",
        root=test_path,
    )
    assert_attrs(
        rooted_path.join_within_root("nonexistent-subpath/.."),
        path=test_path,
        root=test_path,
    )
    assert_attrs(
        rooted_path.join_within_root("nonexistent-subpath", ".."),
        path=test_path,
        root=test_path,
    )
    assert_attrs(
        rooted_path.join_within_root("nonexistent-subpath").join_within_root(".."),
        path=test_path,
        root=test_path,
    )
    assert_attrs(
        rooted_path.join_within_root("subpath").join_within_root("symlink-to-parent"),
        path=test_path,
        root=test_path,
    )


def test_re_root(test_path: Path) -> None:
    rooted_path = RootedPath(test_path)

    assert_attrs(
        rooted_path.re_root("subpath"),
        path=test_path / "subpath",
        root=test_path / "subpath",
    )
    assert_attrs(
        rooted_path.re_root("nonexistent-subpath"),
        path=test_path / "nonexistent-subpath",
        root=test_path / "nonexistent-subpath",
    )


@pytest.mark.parametrize("join_method", ["re_root", "join_within_root"])
def test_dont_leave_root(
    join_method: Literal["re_root", "join_within_root"], test_path: Path
) -> None:
    rooted_path = RootedPath(test_path)

    if join_method == "re_root":
        join = RootedPath.re_root
    else:
        join = RootedPath.join_within_root

    # root/..
    with expect_path_outside_root("..", test_path, test_path):
        join(rooted_path, "..")

    # root/symlink-to-parent
    with expect_path_outside_root("symlink-to-parent", test_path, test_path):
        join(rooted_path, "symlink-to-parent")

    # root/subpath/../..
    with expect_path_outside_root("../..", test_path / "subpath", test_path):
        join(rooted_path.join_within_root("subpath"), "../..")

    # root/subpath/symlink-to-abspath
    with expect_path_outside_root("symlink-to-abspath", test_path / "subpath", test_path):
        join(rooted_path.join_within_root("subpath"), "symlink-to-abspath")

    # root/ /abspath
    with expect_path_outside_root("/abspath", test_path, test_path):
        join(rooted_path, "/abspath")

    # (root/subpath)/..
    with expect_path_outside_root("..", test_path / "subpath", test_path / "subpath"):
        join(rooted_path.re_root("subpath"), "..")


def test_rooted_path_repr() -> None:
    rooted_path = RootedPath("/some/path")
    assert repr(rooted_path) == "<RootedPath root='/some/path' subpath='.'>"
    assert (
        repr(rooted_path.join_within_root("subpath"))
        == "<RootedPath root='/some/path' subpath='subpath'>"
    )
    assert (
        repr(rooted_path.re_root("subpath")) == "<RootedPath root='/some/path/subpath' subpath='.'>"
    )


def test_pydantic_integration() -> None:
    class SomeModel(pydantic.BaseModel):
        path: RootedPath

    x = SomeModel.parse_obj({"path": "/foo"})
    assert isinstance(x.path, RootedPath)
    assert_attrs(x.path, root=Path("/foo"), path=Path("/foo"))

    with pytest.raises(pydantic.ValidationError, match="expected str or os.PathLike, got bytes"):
        SomeModel.parse_obj({"path": b"/foo"})

    with pytest.raises(pydantic.ValidationError, match="path must be absolute: foo/bar"):
        SomeModel.parse_obj({"path": "foo/bar"})
