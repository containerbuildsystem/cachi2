from os import PathLike
from pathlib import Path, PosixPath
from typing import TYPE_CHECKING, TypeVar, Union

from cachi2.core.errors import PackageRejected

if TYPE_CHECKING:
    PathType = PosixPath
else:
    PathType = type(Path())


StrPath = Union[str, PathLike[str]]
SafePathT = TypeVar("SafePathT", bound="SafePath")


class NotSubpath(PackageRejected):
    """Cachi2 expected a subpath, but it wasn't a subpath."""

    def __init__(self, reason: str) -> None:
        """Create a NotSubpath error."""
        super().__init__(reason, solution=None, docs=None)


class SafePath(PathType):
    """A Path subclass with a safer joinpath.

    >>> safe_path = SafePath("/some/directory")

    Subpaths obtained via `safe_path / path` or `safe_path.joinpath(*path_components)`
    must be subpaths of the safe_path. Otherwise, the join operation raises the NotSubpath
    error.
    """

    def __new__(cls: type[SafePathT], abspath: StrPath) -> SafePathT:
        """Create a SafePath. The argument must be an absolute path."""
        path = super().__new__(cls, abspath)
        if not path.is_absolute():
            raise ValueError(f"safe path must be absolute but isn't: {abspath}")
        return path

    def joinpath(self: SafePathT, *other: StrPath) -> SafePathT:
        """Join other components to the SafePath. If the result is not a subpath, raise an error."""
        path = super().joinpath(*other).resolve()
        if not path.is_relative_to(self):
            raise NotSubpath(
                f"supposed subpath ({Path(*other)}) leads outside parent path ({self})"
            )
        return path

    def __truediv__(self: SafePathT, key: StrPath) -> SafePathT:
        """Join a path to the SafePath using the '/' operator.

        Note the difference in behavior between the following styles:

            safe_path / "subpath/.."        OK
            safe_path / "subpath" / ".."    ERROR, .. leads outside {safe_path}/subpath
        """
        return self.joinpath(key)
