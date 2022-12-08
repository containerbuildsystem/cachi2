import pytest

from cachi2.core.checksum import ChecksumInfo, verify_checksum
from cachi2.core.errors import PackageRejected


def test_verify_checksum(tmpdir):
    file = tmpdir.join("spells.txt")
    file.write("Beetlejuice! Beetlejuice! Beetlejuice!")

    expected = {
        "sha512": (
            "da518fe8b800b3325fe35ca680085fe37626414d0916937a01a25ef8f5d7aa769b7233073235fce85ee"
            "c717e02bb9d72062656cf2d79223792a784910c267b54"
        ),
        "sha256": "ed1f8cd69bfacf0528744b6a7084f36e8841b6128de0217503e215612a0ee835",
        "md5": "308764bc995153f7d853827a675e6731",
    }
    for algorithm, checksum in expected.items():
        verify_checksum(str(file), ChecksumInfo(algorithm, checksum))


def test_verify_checksum_invalid_hexdigest(tmpdir):
    file = tmpdir.join("spells.txt")
    file.write("Beetlejuice! Beetlejuice! Beetlejuice!")

    expected_error = "The file spells.txt has an unexpected checksum value"
    with pytest.raises(PackageRejected, match=expected_error):
        verify_checksum(str(file), ChecksumInfo("sha512", "spam"))


def test_verify_checksum_unsupported_algorithm(tmpdir):
    file = tmpdir.join("spells.txt")
    file.write("Beetlejuice! Beetlejuice! Beetlejuice!")

    expected_error = "Cannot perform checksum on the file spells.txt,.*bacon.*"
    with pytest.raises(PackageRejected, match=expected_error):
        verify_checksum(str(file), ChecksumInfo("bacon", "spam"))
