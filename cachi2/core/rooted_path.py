from os import PathLike
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar, Union

from cachi2.core.errors import UsageError


class PathOutsideRoot(UsageError):
    """Afer joining a subpath, the result is outside the root of a rooted path."""

    default_solution = (
        "With security in mind, Cachi2 will not access files outside the "
        "specified source/output directories."
    )


StrPath = Union[str, PathLike[str]]
RootedPathT = TypeVar("RootedPathT", bound="RootedPath")


class RootedPath(PathLike[str]):
    """A safer way to handle subpaths.

    Get a subpath, guaranteeing that it really is a subpath:

    >>> rooted_path = RootedPath("/some/directory")
    >>> rooted_path.join_within_root("..")                  # ERROR PathOutsideRoot
    >>> rooted_path.join_within_root("/abspath")            # ERROR PathOutsideRoot
    >>> rooted_path.join_within_root("symlink-to-parent")   # ERROR PathOutsideRoot

    Access the underlying Path object:

    >>> rooted_path = RootedPath("/some/directory")
    >>> rooted_path.join_within_root("vendor", "modules.txt").path.read_text()

    The join_within_root method remembers the original root. See the join_within_root
    and re_root docstrings for more details.

    Implements the PathLike interface -> most stdlib methods that accept paths will work
    with a RootedPath as well.

    Implements __get_validators__ for pydantic integration.
    """

    def __init__(self, path: StrPath) -> None:
        """Create a RootedPath.

        :param path: the path (which also becomes the root of the RootedPath)
        """
        self._root = Path(path)
        self._path = self.root
        if not self._path.is_absolute():
            raise ValueError(f"path must be absolute: {path}")

    @property
    def root(self) -> Path:
        """Get the root directory which this path is not allowed to leave."""
        return self._root

    @property
    def path(self) -> Path:
        """Get the current path, which is guaranteed to be at or below the root."""
        return self._path

    def __fspath__(self) -> str:
        return self.path.__fspath__()

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:
        typename = type(self).__name__
        subpath_from_root = self.path.relative_to(self.root)
        return f"<{typename} root={str(self.root)!r} subpath={str(subpath_from_root)!r}>"

    def re_root(self: RootedPathT, *other: StrPath) -> RootedPathT:
        """Safely join other path components and make the result the new root.

        >>> rooted_path = RootedPath("/some/directory")
        >>> rooted_path.re_root("subpath").join_within_root("..")   # ERROR

        :raises PathOutsideRoot: if the resulting path is not a subpath of the root
        """
        subpath = self.path.joinpath(*other).resolve()
        if not subpath.is_relative_to(self.root):
            s_other = str(Path(*other))
            s_self = str(self)
            s_root = str(self.root)
            raise PathOutsideRoot(
                f"Joining path {s_other!r} to {s_self!r}: target is outside {s_root!r}"
            )
        cls = type(self)
        return cls(subpath)

    def join_within_root(self: RootedPathT, *other: StrPath) -> RootedPathT:
        """Safely join other path components but remember the original root.

        >>> rooted_path = RootedPath("/some/directory")
        >>> rooted_path.join_within_root("subpath").join_within_root("..")  # OK

        :raises PathOutsideRoot: if the resulting path is not a subpath of the root
        """
        new = self.re_root(*other)
        new._root = self.root
        return new

    # pydantic integration
    @classmethod
    def __get_validators__(cls: type[RootedPathT]) -> Iterator[Callable[[Any], RootedPathT]]:
        yield cls._validate

    @classmethod
    def _validate(cls: type[RootedPathT], v: Any) -> RootedPathT:
        if not isinstance(v, (str, PathLike)):
            raise TypeError(f"expected str or os.PathLike, got {type(v).__name__}")
        return cls(v)
