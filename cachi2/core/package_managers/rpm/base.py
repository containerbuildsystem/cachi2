from os import PathLike
from typing import Any, TypeVar, Union

from pydantic import BaseModel

from cachi2.core.rooted_path import RootedPath

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


class RpmsLock:
    def __init__(self, content: dict[str, Any]) -> None:
        self._content = content  # raw content of the lockfile (text)
        # lockfile structure after parsing and pydantic validation
        self._lockfile: BaseModelT = None
        # metadata of file records found in the lockfile (for verification and SBOM generation)
        self._files_metadata: dict[Union[str, PathLike[str]], Any] = {}

    def is_valid(self) -> bool:
        return self._lockfile is not None and self._lockfile

    @property
    def metadata(self) -> dict[Union[str, PathLike[str]], Any]:
        return self._files_metadata

    def match_format(self) -> bool:
        raise NotImplementedError

    def process_format(self) -> None:
        raise NotImplementedError

    def download(self, output_dir: RootedPath) -> None:
        raise NotImplementedError


RpmsLockT = TypeVar("RpmsLockT", bound=RpmsLock)
