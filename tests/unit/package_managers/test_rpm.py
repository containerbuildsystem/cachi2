from unittest import mock

import pytest
import yaml

from cachi2.core.errors import PackageManagerError, PackageRejected
from cachi2.core.package_managers.rpm import fetch_rpm_source
from cachi2.core.package_managers.rpm.main import DEFAULT_LOCKFILE_NAME, _resolve_rpm_project
from cachi2.core.package_managers.rpm.redhat import RedhatRpmsLock
from cachi2.core.rooted_path import RootedPath


@mock.patch("cachi2.core.package_managers.rpm.main.RequestOutput.from_obj_list")
@mock.patch("cachi2.core.package_managers.rpm.main._resolve_rpm_project")
def test_fetch_rpm_source(
    mock_resolve_rpm_project: mock.Mock,
    mock_from_obj_list: mock.Mock,
) -> None:
    mock_component = mock.Mock()
    mock_resolve_rpm_project.return_value = [mock_component]
    mock_request = mock.Mock()
    mock_request.rpm_packages = [mock.Mock()]
    fetch_rpm_source(mock_request)
    mock_resolve_rpm_project.assert_called_once()
    mock_from_obj_list.assert_called_once_with(
        components=[mock_component], environment_variables=[], project_files=[]
    )


def test_resolve_rpm_project_no_lockfile(rooted_tmp_path: RootedPath) -> None:
    with pytest.raises(PackageRejected) as exc_info:
        mock_source_dir = mock.Mock()
        mock_source_dir.join_within_root.return_value.path.exists.return_value = False
        _resolve_rpm_project(mock_source_dir, mock.Mock())
    assert f"RPM lockfile '{DEFAULT_LOCKFILE_NAME}' missing, refusing to continue" in str(
        exc_info.value
    )


def test_resolve_rpm_project_invalid_yaml_format(rooted_tmp_path: RootedPath) -> None:
    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        # colon is missing at the end
        f.write("lockfileVendor: redhat\nlockfileVersion: 1\narches\n")
    with pytest.raises(PackageRejected) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)

    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        # end of line is missing between items
        f.write("lockfileVendor: redhat lockfileVersion: 1\narches:\n")
    with pytest.raises(PackageRejected) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)
    assert f"RPM lockfile '{DEFAULT_LOCKFILE_NAME}' yaml format is not correct" in str(
        exc_info.value
    )


def test_resolve_rpm_project_invalid_lockfile_format(rooted_tmp_path: RootedPath) -> None:
    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "unknown",
                "lockfileVersion": 1,
                "arches": [],
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)

    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "redhat",
                "lockfileVersion": 2,
                "arches": [],
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)

    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "redhat",
                "lockfileVersion": "zz",
                "arches": [],
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)

    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "vendor": "redhat",
                "lockfileVersion": 1,
                "arches": [],
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)

    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "redhat",
                "lockfileVersion": 1,
                "arches": "everything",
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)

    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "redhat",
                "lockfileVersion": "zz",
                "arches": [
                    {
                        "arch": "x86_64",
                        "packages": [
                            {
                                "address": "SOME_ADDRESS",
                                "size": 1111,
                            },
                        ],
                    },
                ],
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)
    assert f"RPM lockfile '{DEFAULT_LOCKFILE_NAME}' format is not valid" in str(exc_info.value)


def test_resolve_rpm_project_arch_empty(rooted_tmp_path: RootedPath) -> None:
    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "redhat",
                "lockfileVersion": 1,
                "arches": [
                    {
                        "arch": "x86_64",
                    },
                ],
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)

    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "redhat",
                "lockfileVersion": 1,
                "arches": [
                    {
                        "arch": "aarch64",
                        "packages": [],
                    },
                ],
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)

    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "redhat",
                "lockfileVersion": 1,
                "arches": [
                    {
                        "arch": "i686",
                        "packages": [],
                        "source": [],
                    },
                    {
                        "arch": "x86_64",
                        "packages": [
                            {
                                "url": "SOME_URL",
                            },
                        ],
                    },
                ],
            },
            f,
        )
    with pytest.raises(PackageManagerError) as exc_info:
        _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)
    assert "At least one field ('packages', 'source') must be set in every arch." in str(
        exc_info.value
    )


def test_resolve_rpm_project_correct_format(rooted_tmp_path: RootedPath) -> None:
    with open(rooted_tmp_path.join_within_root("rpms.lock.yaml"), "w") as f:
        yaml.safe_dump(
            {
                "lockfileVendor": "redhat",
                "lockfileVersion": 1,
                "arches": [
                    {
                        "arch": "x86_64",
                        "packages": [
                            {
                                "url": "SOME_URL",
                            },
                        ],
                        "source": [
                            {
                                "url": "SOME_URL",
                            },
                        ],
                    },
                ],
            },
            f,
        )
    _resolve_rpm_project(rooted_tmp_path, rooted_tmp_path)


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
