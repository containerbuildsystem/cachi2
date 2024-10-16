import os
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator

from cachi2.core.checksum import ChecksumInfo


class LockfileMetadata(BaseModel):
    """Defines format of the metadata section in the lockfile."""

    version: Literal["1.0"]


class LockfileArtifact(BaseModel):
    """
    Defines format of a single artifact in the lockfile.

    Only used for validation of the format of the lockfile.
    """

    download_url: str
    target: Optional[str] = None
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


class GenericLockfileV1(BaseModel):
    """Defines format of the cachi2 generic lockfile, version 1.0."""

    metadata: LockfileMetadata
    artifacts: list[LockfileArtifact]


class GenericArtifact(BaseModel):
    """Lockfile-version-independent representation of an artifact."""

    download_url: str
    target: Optional[str] = None
    checksums: dict[str, str]
    resolved_path: Optional[os.PathLike[str]] = None

    @classmethod
    def from_lockfile_artifact(cls, artifact: LockfileArtifact) -> "GenericArtifact":
        """
        Create a GenericArtifact from a LockfileArtifact.

        :param artifact: the LockfileArtifact to convert
        :return: the new GenericArtifact
        """
        return cls(
            download_url=artifact.download_url,
            target=artifact.target,
            checksums=artifact.checksums,
        )

    @property
    def formatted_checksums(self) -> List[ChecksumInfo]:
        """Return the checksums as a list of ChecksumInfo objects."""
        return [ChecksumInfo(algo, digest) for algo, digest in self.checksums.items()]

    @property
    def resolved_target(self) -> str:
        """Return the computed target file of the artifact, either set, or taken from the download URL."""
        return self.target if self.target else os.path.basename(self.download_url)

    def has_same_resolved_path(self, resolved_path: os.PathLike[str]) -> bool:
        """Compare the resolved paths of two artifacts, if they are set."""
        # if the path hasn't been set yet, we're unable to compare
        if self.resolved_path is None or resolved_path is None:
            return False

        return os.path.realpath(self.resolved_path) == os.path.realpath(resolved_path)
