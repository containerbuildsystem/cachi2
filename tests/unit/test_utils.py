import hashlib

import pytest

from cachi2._compat.errors import UnknownHashAlgorithm
from cachi2.core.utils import hash_file


def test_get_unknown_hash_algorithm():
    with pytest.raises(UnknownHashAlgorithm):
        hash_file("some_file.tar", algorithm="xxx")


@pytest.mark.parametrize("file_content", ["", "abc123" * 100])
@pytest.mark.parametrize("algorithm", [None, "sha512"])
def test_hash_file(file_content, algorithm, tmpdir):
    data_file = tmpdir.join("file.data")
    data_file.write(file_content)

    if algorithm is None:
        hasher = hash_file(str(data_file))
        assert hashlib.sha256(file_content.encode()).digest() == hasher.digest()
    else:
        hasher = hash_file(str(data_file), algorithm=algorithm)
        h = hashlib.new(algorithm)
        h.update(file_content.encode())
        assert h.digest() == hasher.digest()
