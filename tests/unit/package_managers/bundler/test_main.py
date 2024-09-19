import pytest
from git.repo import Repo

from cachi2.core.errors import PackageRejected
from cachi2.core.package_managers.bundler.main import _get_main_package_name_and_version
from cachi2.core.package_managers.bundler.parser import GemDependency, ParseResult, PathDependency
from cachi2.core.rooted_path import RootedPath


def test_get_main_package_name_and_version(rooted_tmp_path: RootedPath) -> None:
    dependencies: ParseResult = [
        GemDependency(
            name="my_gem_dep",
            version="0.1.0",
            source="https://rubygems.org",
        ),
        PathDependency(
            name="my_path_dep",
            version="0.2.0",
            subpath=".",
        ),
    ]

    name, version = _get_main_package_name_and_version(
        package_dir=rooted_tmp_path, dependencies=dependencies
    )
    assert name == "my_path_dep"
    assert version == "0.2.0"


def test_get_main_package_name_and_version_from_repo(rooted_tmp_path_repo: RootedPath) -> None:
    repo = Repo(rooted_tmp_path_repo)
    repo.create_remote("origin", "git@github.com:user/example.git")

    name, version = _get_main_package_name_and_version(
        package_dir=rooted_tmp_path_repo, dependencies=[]
    )

    assert name == "example"
    assert version is None


def test_get_main_package_name_and_version_from_repo_without_origin(
    rooted_tmp_path_repo: RootedPath,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(PackageRejected) as exc_info:
        _get_main_package_name_and_version(package_dir=rooted_tmp_path_repo, dependencies=[])

    assert "Failed to extract package name from origin remote" in exc_info.value.friendly_msg()
