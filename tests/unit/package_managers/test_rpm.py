from unittest import mock

import pytest

from cachi2.core.package_managers.rpm.redhat import RedhatRpmsLock


class TestRedhatRpmsLock:
    @pytest.fixture
    def raw_content(self) -> dict:
        return {"lockfileVendor": "redhat", "lockfileVersion": 1, "arches": []}

    @mock.patch("cachi2.core.package_managers.rpm.redhat.uuid")
    def test_internal_repoid(self, mock_uuid: mock.Mock, raw_content: dict) -> None:
        mock_uuid.uuid4.return_value.hex = "abcdefghijklmn"
        lock = RedhatRpmsLock.model_validate(raw_content)
        assert lock._uuid == "abcdef"
        assert lock.internal_repoid == "cachi2-abcdef"

    @mock.patch("cachi2.core.package_managers.rpm.redhat.uuid")
    def test_internal_source_repoid(self, mock_uuid: mock.Mock, raw_content: dict) -> None:
        mock_uuid.uuid4.return_value.hex = "abcdefghijklmn"
        lock = RedhatRpmsLock.model_validate(raw_content)
        assert lock._uuid == "abcdef"
        assert lock.internal_source_repoid == "cachi2-abcdef-source"

    def test_uuid(self, raw_content: dict) -> None:
        lock = RedhatRpmsLock.model_validate(raw_content)
        uuid = lock._uuid
        assert len(uuid) == 6
