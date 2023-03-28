from os import PathLike
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar, Union

from cachi2.core.errors import PackageRejected

StrPath = Union[str, PathLike[str]]
RootedPathT = TypeVar("RootedPathT", bound="RootedPath")


class NotSubpath(PackageRejected):
    """Cachi2 expected a subpath, but it wasn't a subpath."""

    def __init__(self, reason: str) -> None:
        """Create a NotSubpath error."""
        super().__init__(reason, solution=None, docs=None)


class RootedPath(PathLike[str]):
    """A safer way to handle subpaths.

    Get a subpath, guaranteeing that it really is a subpath:

    >>> rooted_path = RootedPath("/some/directory")
    >>> rooted_path.join_within_root("..")                  # ERROR NotSubpath
    >>> rooted_path.join_within_root("/abspath")            # ERROR NotSubpath
    >>> rooted_path.join_within_root("symlink-to-parent")   # ERROR NotSubpath

    Access the underlying Path object:

    >>> rooted_path = RootedPath("/some/directory")
    >>> rooted_path.join_within_root("vendor", "modules.txt").path.read_text()

    The join_within_root method remembers the original root. See the join_within_root
    and re_root docstrings for more details.
    """

    def __init__(self, path: StrPath) -> None:
        """Create a RootedPath. The argument must be an absolute path."""
        self._path = Path(path)
        self._root = self._path
        if not self._path.is_absolute():
            raise ValueError(f"path must be absolute: {path}")

    @property
    def root(self) -> Path:
        """Get the root directory which this path is not allowed to leave."""
        return self._root

    @property
    def path(self) -> Path:
        """Get the current path (guaranteed to be at or below the root)."""
        return self._path

    def __fspath__(self) -> str:
        return self.path.__fspath__()

    def __str__(self) -> str:
        return str(self.path)

    def re_root(self: RootedPathT, *other: StrPath) -> RootedPathT:
        """Safely join other path components and make the result the new root.

        >>> rooted_path = RootedPath("/some/directory")
        >>> rooted_path.re_root("subpath").join_within_root("..")      # ERROR
        """
        subpath = self.path.joinpath(*other).resolve()
        if not subpath.is_relative_to(self.root):
            subpath_from_root = self.path.relative_to(self.root).joinpath(*other)
            raise NotSubpath(
                f"supposed subpath ({subpath_from_root}) leads outside root path ({self.root})"
            )
        cls = type(self)
        return cls(subpath)

    def join_within_root(self: RootedPathT, *other: StrPath) -> RootedPathT:
        """Safely join other path components but remember the original root.

        >>> rooted_path = RootedPath("/some/directory")
        >>> rooted_path.join_within_root("subpath").join_within_root("..")    # OK
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
        return cls(Path(v))
