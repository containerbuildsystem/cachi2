from collections import Counter
from pathlib import Path
from typing import List, Literal
from urllib.parse import urlparse

from pydantic import AnyUrl, BaseModel, field_validator, model_validator
from pydantic_core.core_schema import ValidationInfo

from cachi2.core.checksum import ChecksumInfo
from cachi2.core.errors import PackageManagerError
from cachi2.core.rooted_path import RootedPath


class LockfileMetadata(BaseModel):
    """Defines format of the metadata section in the lockfile."""

    version: Literal["1.0"]


class LockfileArtifact(BaseModel):
    """
    Defines format of a single artifact in the lockfile.

    :param download_url: The URL to download the artifact from.
    :param filename: The target path to save the artifact to. Subpath of the deps/generic folder.
    :param checksums: Map that represents checksums for the artifact where keys are hashing algs and values are hashes.
    """

    download_url: AnyUrl
    filename: str = ""
    checksums: dict[str, str]

    @field_validator("checksums")
    @classmethod
    def no_empty_checksums(cls, value: dict[str, str]) -> dict[str, str]:
        """
        Validate that at least one checksum is present for an artifact.

        :param value: the checksums dict to validate
        :return: the validated checksum dict
        """
        if len(value) == 0:
            raise ValueError("At least one checksum must be provided.")
        return value

    @model_validator(mode="after")
    def set_filename(self, info: ValidationInfo) -> "LockfileArtifact":
        """Set the target path if not provided and resolve it into an absolute path."""
        if not self.filename:
            url_path = urlparse(str(self.download_url)).path
            self.filename = Path(url_path).name

        # needs to have output_dir context in order to be able to resolve the target path
        # and so that it can be used to check for conflicts with other artifacts
        if not info.context or "output_dir" not in info.context:
            raise PackageManagerError(
                "The `LockfileArtifact` class needs to be called with `output_dir` in the context"
            )
        output_dir: RootedPath = info.context["output_dir"]
        self.filename = str(output_dir.join_within_root(self.filename).path.resolve())

        return self

    @property
    def formatted_checksums(self) -> List[ChecksumInfo]:
        """Return the checksums as a list of ChecksumInfo objects."""
        return [ChecksumInfo(algo, digest) for algo, digest in self.checksums.items()]


class GenericLockfileV1(BaseModel):
    """Defines format of the cachi2 generic lockfile, version 1.0."""

    metadata: LockfileMetadata
    artifacts: list[LockfileArtifact]

    @model_validator(mode="after")
    def no_artifact_conflicts(self) -> "GenericLockfileV1":
        """Validate that all artifacts have unique filenames and download_urls."""
        urls = Counter(a.download_url for a in self.artifacts)
        filenames = Counter(a.filename for a in self.artifacts)
        duplicate_urls = [str(u) for u, count in urls.most_common() if count > 1]
        duplicate_filenames = [t for t, count in filenames.most_common() if count > 1]
        if duplicate_urls or duplicate_filenames:
            raise ValueError(
                (f"Duplicate download_urls: {duplicate_urls}\n" if duplicate_urls else "")
                + (f"Duplicate filenames: {duplicate_filenames}" if duplicate_filenames else "")
            )

        return self
