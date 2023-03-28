from os import PathLike
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar, Union

from cachi2.core.errors import PackageRejected

StrPath = Union[str, PathLike[str]]
SafePathT = TypeVar("SafePathT", bound="SafePath")


class NotSubpath(PackageRejected):
    """Cachi2 expected a subpath, but it wasn't a subpath."""

    def __init__(self, reason: str) -> None:
        """Create a NotSubpath error."""
        super().__init__(reason, solution=None, docs=None)


class SafePath(PathLike[str]):
    """A safer way to handle subpaths.

    Get a subpath, guaranteeing that it really is a subpath:

    >>> safe_path = SafePath("/some/directory")
    >>> safe_path.safe_join("..")                   # ERROR NotSubpath
    >>> safe_path.safe_join("/abspath")             # ERROR NotSubpath
    >>> safe_path.safe_join("symlink-to-parent")    # ERROR NotSubpath

    Access the underlying Path object:

    >>> safe_path = SafePath("/some/directory")
    >>> safe_path.safe_join("vendor", "modules.txt").path.read_text()
    """

    def __init__(self, path: StrPath) -> None:
        """Create a SafePath. The argument must be an absolute path."""
        self._path = Path(path)
        if not self._path.is_absolute():
            raise ValueError(f"path must be absolute: {path}")

    @property
    def path(self) -> Path:
        """Get the underlying Path object."""
        return self._path

    def __fspath__(self) -> str:
        return self.path.__fspath__()

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self.path)!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, type(self)) and self.path == other.path

    def __hash__(self) -> int:
        return hash(self.path)

    def safe_join(self: SafePathT, *other: StrPath) -> SafePathT:
        """Join other components to the SafePath. If the result is not a subpath, raise an error."""
        subpath = self.path.joinpath(*other).resolve()
        if not subpath.is_relative_to(self):
            raise NotSubpath(
                f"supposed subpath ({Path(*other)}) leads outside parent path ({self})"
            )
        cls = type(self)
        return cls(subpath)

    # pydantic integration
    @classmethod
    def __get_validators__(cls: type[SafePathT]) -> Iterator[Callable[[Any], SafePathT]]:
        yield cls._validate

    @classmethod
    def _validate(cls: type[SafePathT], v: Any) -> SafePathT:
        if not isinstance(v, (str, PathLike)):
            raise TypeError(f"expected str or os.PathLike, got {type(v).__name__}")
        return cls(Path(v))
