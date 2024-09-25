from pathlib import Path
from unittest import mock

import pytest

from cachi2.core.errors import PackageRejected
from cachi2.core.models.input import YarnClassicPackageInput
from cachi2.core.package_managers.yarn_classic.workspaces import (
    Workspace,
    extract_workspace_metadata,
    extract_workspaces_globs,
    get_workspace_paths,
)
from cachi2.core.rooted_path import RootedPath


@mock.patch("cachi2.core.package_managers.yarn_classic.workspaces.read_package_from")
@mock.patch("cachi2.core.package_managers.yarn_classic.workspaces.get_workspace_paths")
def test_packages_with_workspaces_outside_source_dir_are_rejected(
    mock_get_ws_paths: mock.Mock,
    mock_read_package_from: mock.Mock,
) -> None:
    package = YarnClassicPackageInput(type="yarn-classic", path=".")
    mock_read_package_from.return_value = {"workspaces": ["../../usr"]}
    mock_get_ws_paths.return_value = [Path("/tmp/foo/bar"), Path("/usr")]
    source_dir = RootedPath("/tmp/foo")

    with pytest.raises(PackageRejected):
        extract_workspace_metadata(package, source_dir=source_dir)


@mock.patch("cachi2.core.package_managers.yarn_classic.workspaces.read_package_from")
@mock.patch("cachi2.core.package_managers.yarn_classic.workspaces.get_workspace_paths")
@mock.patch(
    "cachi2.core.package_managers.yarn_classic.workspaces.ensure_workspaces_are_well_formed"
)
def test_workspaces_could_be_parsed(
    mock_workspaces_ok: mock.Mock,
    mock_get_ws_paths: mock.Mock,
    mock_read_package_from: mock.Mock,
) -> None:
    package = YarnClassicPackageInput(type="yarn-classic", path=".")
    mock_read_package_from.side_effect = [{"workspaces": ["quux"]}, {"name": "inner_package"}]
    mock_get_ws_paths.return_value = [Path("/tmp/foo/bar")]
    source_dir = RootedPath("/tmp/foo")

    expected_result = [
        Workspace(
            path="/tmp/foo/bar",
            package=YarnClassicPackageInput(type="yarn-classic", path=Path("bar")),
            package_contents={"name": "inner_package"},
        ),
    ]
    result = extract_workspace_metadata(package, source_dir=source_dir)

    assert result == expected_result


def test_extracting_workspace_globs_works_with_globs_deined_in_list() -> None:
    package = {"workspaces": ["foo"]}

    expected = ["foo"]
    result = extract_workspaces_globs(package)

    assert expected == result


def test_extracting_workspace_globs_works_with_glons_defined_in_dict() -> None:
    package = {"workspaces": {"packages": ["foo"]}}

    expected = ["foo"]
    result = extract_workspaces_globs(package)

    assert expected == result


def test_workspace_paths_could_be_resolved(rooted_tmp_path: RootedPath) -> None:
    expected = rooted_tmp_path.path / "foo"
    expected.mkdir()

    result = list(get_workspace_paths(["foo"], rooted_tmp_path))

    assert result == [expected]
