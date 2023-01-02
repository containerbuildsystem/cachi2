from pathlib import Path
from typing import Literal

import pytest

from cachi2.core.checksum import SUPPORTED_ALGORITHMS, ChecksumInfo, must_match_any_checksum
from cachi2.core.errors import PackageRejected

FILE_CONTENT = "Beetlejuice! Beetlejuice! Beetlejuice!"

SHA512 = "da518fe8b800b3325fe35ca680085fe37626414d0916937a01a25ef8f5d7aa769b7233073235fce85eec717e02bb9d72062656cf2d79223792a784910c267b54"  # noqa: line-too-long
SHA256 = "ed1f8cd69bfacf0528744b6a7084f36e8841b6128de0217503e215612a0ee835"
MD5 = "308764bc995153f7d853827a675e6731"

SUPPORTED_ALG_STR = ", ".join(sorted(SUPPORTED_ALGORITHMS))

AlgorithmName = Literal["sha256", "sha512", "md5"]


def correct(algorithm: AlgorithmName) -> ChecksumInfo:
    digest = {"sha256": SHA256, "sha512": SHA512, "md5": MD5}[algorithm]
    return ChecksumInfo(algorithm, digest)


def wrong(algorithm: AlgorithmName) -> ChecksumInfo:
    hexlen = {"sha256": 64, "sha512": 128, "md5": 32}[algorithm]
    wrong_digest = "a" * hexlen
    return ChecksumInfo(algorithm, wrong_digest)


unknown = ChecksumInfo("sha0", "a" * 40)


@pytest.mark.parametrize(
    "checksums, expect_log_msg",
    [
        (
            [correct("sha256")],
            f"sha256 checksum matches: {SHA256}",
        ),
        (
            [correct("sha512")],
            f"sha512 checksum matches: {SHA512}",
        ),
        (
            [correct("md5")],
            f"md5 checksum matches: {MD5}",
        ),
        (
            [correct("sha256"), correct("sha512")],
            f"sha256 checksum matches: {SHA256}",
        ),
        (
            [correct("sha512"), correct("sha256")],
            f"sha512 checksum matches: {SHA512}",
        ),
        (
            [wrong("sha256"), correct("sha256")],
            f"sha256 checksum matches: {SHA256}",
        ),
        (
            [wrong("sha512"), correct("sha256")],
            f"sha256 checksum matches: {SHA256}",
        ),
        (
            [unknown, correct("sha256")],
            f"sha256 checksum matches: {SHA256}",
        ),
        (
            # sha256 is computed first and maches the one later in the list
            [wrong("sha256"), correct("sha512"), correct("sha256")],
            f"sha256 checksum matches: {SHA256}",
        ),
    ],
)
def test_verify_checksum(
    checksums: list[ChecksumInfo],
    expect_log_msg: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    file = tmp_path.joinpath("spells.txt")
    file.write_text(FILE_CONTENT)
    caplog.set_level("DEBUG")

    must_match_any_checksum(file, checksums)

    assert caplog.messages == [f"spells.txt: {expect_log_msg}"]


@pytest.mark.parametrize(
    "checksums, expect_log_msgs",
    [
        (
            [wrong("sha256")],
            [f"sha256 checksum does not match (got: {SHA256})"],
        ),
        (
            [wrong("sha512")],
            [f"sha512 checksum does not match (got: {SHA512})"],
        ),
        (
            [wrong("md5")],
            [f"md5 checksum does not match (got: {MD5})"],
        ),
        (
            [unknown],
            [f"sha0 checksum not supported (supported: {SUPPORTED_ALG_STR})"],
        ),
        (
            [wrong("sha256"), wrong("sha512"), unknown],
            [
                f"sha256 checksum does not match (got: {SHA256})",
                f"sha512 checksum does not match (got: {SHA512})",
                f"sha0 checksum not supported (supported: {SUPPORTED_ALG_STR})",
            ],
        ),
        (
            # log the mismatch for each algorithm only once
            [
                ChecksumInfo("sha256", "bad1"),
                ChecksumInfo("sha256", "bad2"),
                ChecksumInfo("sha512", "bad3"),
                ChecksumInfo("sha512", "bad4"),
            ],
            [
                f"sha256 checksum does not match (got: {SHA256})",
                f"sha512 checksum does not match (got: {SHA512})",
            ],
        ),
    ],
)
def test_verify_checksum_failure(
    checksums: list[ChecksumInfo],
    expect_log_msgs: list[str],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
):
    file = tmp_path.joinpath("spells.txt")
    file.write_text(FILE_CONTENT)
    caplog.set_level("WARNING")

    with pytest.raises(PackageRejected, match="Failed to verify spells.txt"):
        must_match_any_checksum(file, checksums)

    expect_messages = [f"spells.txt: {msg}" for msg in expect_log_msgs]
    assert caplog.messages == expect_messages
