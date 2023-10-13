import json
from typing import Any
from unittest import mock

import pytest

from cachi2.core.errors import UnsupportedFeature
from cachi2.core.package_managers.yarn.locators import parse_locator
from cachi2.core.package_managers.yarn.resolver import Package, resolve_packages
from cachi2.core.rooted_path import RootedPath


def mock_yarn_info_output(yarn_info_outputs: list[dict[str, Any]]) -> str:
    yarn_info_string_output = "\n".join(
        json.dumps(obj, separators=(",", ":")) for obj in yarn_info_outputs
    )
    return yarn_info_string_output + "\n"


# re-generate using hack/mock-unittest-data/yarn.py
YARN_INFO_OUTPUTS = [
    {
        "value": "@isaacs/cliui@npm:8.0.2",
        "children": {
            "Version": "8.0.2",
            "Cache": {
                "Checksum": "8/4a473b9b32a7d4d3cfb7a614226e555091ff0c5a29a1734c28c72a182c2f6699b26fc6b5c2131dfd841e86b185aea714c72201d7c98c2fba5f17709333a67aeb",
                "Path": "{repo_dir}/.yarn/cache/@isaacs-cliui-npm-8.0.2-f4364666d5-4a473b9b32.zip",
                "Size": 10582,
            },
        },
    },
    {
        "value": "ansi-regex-link@link:external-packages/ansi-regex::locator=berryscary%40workspace%3A.",
        "children": {"Version": "0.0.0-use.local", "Cache": {"Checksum": None, "Path": None}},
    },
    {
        "value": "berryscary@workspace:.",
        "children": {
            "Instances": 1,
            "Version": "0.0.0-use.local",
            "Cache": {"Checksum": None, "Path": None},
            "Exported Binaries": ["berryscary"],
        },
    },
    {
        "value": "c2-wo-deps-2@https://bitbucket.org/cachi-testing/cachi2-without-deps-second/get/09992d418fc44a2895b7a9ff27c4e32d6f74a982.tar.gz",
        "children": {
            "Version": "2.0.0",
            "Cache": {
                "Checksum": "8/b194fd1f4a79472a332fec936818d1713a222157e845a8d466a239fdc950130a7ad9b77c212d69d2947c07bce0c911446496ff47dec5a73b4368f0a9c9432b1d",
                "Path": "{repo_dir}/.yarn/cache/c2-wo-deps-2-https-4261b189d8-b194fd1f4a.zip",
                "Size": 1925,
            },
        },
    },
    {
        "value": "fsevents@patch:fsevents@npm%3A2.3.2#./my-patches/fsevents.patch::version=2.3.2&hash=cf0bf0&locator=berryscary%40workspace%3A.",
        "children": {
            "Version": "2.3.2",
            "Cache": {
                "Checksum": "8/f73215b04b52395389a612af4d30f7f412752cdfba1580c9e32c7ec259e448b57b464a4d0474427d6142f5ed9a6260fc1841d61834caf44706d77874fba6f17f",
                "Path": "{repo_dir}/.yarn/cache/fsevents-patch-9d1204d729-f73215b04b.zip",
                "Size": 22847,
            },
        },
    },
    {
        "value": "fsevents@patch:fsevents@patch%3Afsevents@npm%253A2.3.2%23./my-patches/fsevents.patch%3A%3Aversion=2.3.2&hash=cf0bf0&locator=berryscary%2540workspace%253A.#~builtin<compat/fsevents>::version=2.3.2&hash=df0bf1",
        "children": {
            "Version": "2.3.2",
            "Cache": {
                "Checksum": None,
                "Path": "{repo_dir}/.yarn/cache/fsevents-patch-e4409ad759-8.zip",
            },
        },
    },
    {
        "value": "old-man-from-scene-24@workspace:packages/old-man-from-scene-24",
        "children": {"Version": "0.0.0-use.local", "Cache": {"Checksum": None, "Path": None}},
    },
    {
        "value": "once-portal@portal:external-packages/once::locator=berryscary%40workspace%3A.",
        "children": {"Version": "0.0.0-use.local", "Cache": {"Checksum": None, "Path": None}},
    },
    {
        "value": "strip-ansi-tarball@file:../../external-packages/strip-ansi-4.0.0.tgz::locator=the-answer%40workspace%3Apackages%2Fthe-answer",
        "children": {
            "Version": "4.0.0",
            "Cache": {
                "Checksum": "8/d67629c87783bc1138a64f6495439b40f568424a05e068c341b4fc330745e8ba6e7f93536549883054c1da58761f0ce6ab039a233014b38240304d3c45f85ac6",
                "Path": "{repo_dir}/.yarn/cache/strip-ansi-tarball-file-489a50cded-d67629c877.zip",
                "Size": 2419,
            },
        },
    },
    {
        "value": "strip-ansi-tarball@file:external-packages/strip-ansi-4.0.0.tgz::locator=berryscary%40workspace%3A.",
        "children": {
            "Version": "4.0.0",
            "Cache": {
                "Checksum": "8/d67629c87783bc1138a64f6495439b40f568424a05e068c341b4fc330745e8ba6e7f93536549883054c1da58761f0ce6ab039a233014b38240304d3c45f85ac6",
                "Path": "{repo_dir}/.yarn/cache/strip-ansi-tarball-file-3176cc06fb-d67629c877.zip",
                "Size": 2419,
            },
        },
    },
]


EXPECT_PACKAGES = [
    Package(
        raw_locator="@isaacs/cliui@npm:8.0.2",
        version="8.0.2",
        checksum="4a473b9b32a7d4d3cfb7a614226e555091ff0c5a29a1734c28c72a182c2f6699b26fc6b5c2131dfd841e86b185aea714c72201d7c98c2fba5f17709333a67aeb",
        cache_path="{repo_dir}/.yarn/cache/@isaacs-cliui-npm-8.0.2-f4364666d5-4a473b9b32.zip",
    ),
    Package(
        raw_locator="ansi-regex-link@link:external-packages/ansi-regex::locator=berryscary%40workspace%3A.",
        version=None,
        checksum=None,
        cache_path=None,
    ),
    Package(raw_locator="berryscary@workspace:.", version=None, checksum=None, cache_path=None),
    Package(
        raw_locator="c2-wo-deps-2@https://bitbucket.org/cachi-testing/cachi2-without-deps-second/get/09992d418fc44a2895b7a9ff27c4e32d6f74a982.tar.gz",
        version="2.0.0",
        checksum="b194fd1f4a79472a332fec936818d1713a222157e845a8d466a239fdc950130a7ad9b77c212d69d2947c07bce0c911446496ff47dec5a73b4368f0a9c9432b1d",
        cache_path="{repo_dir}/.yarn/cache/c2-wo-deps-2-https-4261b189d8-b194fd1f4a.zip",
    ),
    Package(
        raw_locator="fsevents@patch:fsevents@npm%3A2.3.2#./my-patches/fsevents.patch::version=2.3.2&hash=cf0bf0&locator=berryscary%40workspace%3A.",
        version="2.3.2",
        checksum="f73215b04b52395389a612af4d30f7f412752cdfba1580c9e32c7ec259e448b57b464a4d0474427d6142f5ed9a6260fc1841d61834caf44706d77874fba6f17f",
        cache_path="{repo_dir}/.yarn/cache/fsevents-patch-9d1204d729-f73215b04b.zip",
    ),
    Package(
        raw_locator="fsevents@patch:fsevents@patch%3Afsevents@npm%253A2.3.2%23./my-patches/fsevents.patch%3A%3Aversion=2.3.2&hash=cf0bf0&locator=berryscary%2540workspace%253A.#~builtin<compat/fsevents>::version=2.3.2&hash=df0bf1",
        version="2.3.2",
        checksum=None,
        cache_path="{repo_dir}/.yarn/cache/fsevents-patch-e4409ad759-8.zip",
    ),
    Package(
        raw_locator="old-man-from-scene-24@workspace:packages/old-man-from-scene-24",
        version=None,
        checksum=None,
        cache_path=None,
    ),
    Package(
        raw_locator="once-portal@portal:external-packages/once::locator=berryscary%40workspace%3A.",
        version=None,
        checksum=None,
        cache_path=None,
    ),
    Package(
        raw_locator="strip-ansi-tarball@file:../../external-packages/strip-ansi-4.0.0.tgz::locator=the-answer%40workspace%3Apackages%2Fthe-answer",
        version="4.0.0",
        checksum="d67629c87783bc1138a64f6495439b40f568424a05e068c341b4fc330745e8ba6e7f93536549883054c1da58761f0ce6ab039a233014b38240304d3c45f85ac6",
        cache_path="{repo_dir}/.yarn/cache/strip-ansi-tarball-file-489a50cded-d67629c877.zip",
    ),
    Package(
        raw_locator="strip-ansi-tarball@file:external-packages/strip-ansi-4.0.0.tgz::locator=berryscary%40workspace%3A.",
        version="4.0.0",
        checksum="d67629c87783bc1138a64f6495439b40f568424a05e068c341b4fc330745e8ba6e7f93536549883054c1da58761f0ce6ab039a233014b38240304d3c45f85ac6",
        cache_path="{repo_dir}/.yarn/cache/strip-ansi-tarball-file-3176cc06fb-d67629c877.zip",
    ),
]


@mock.patch("cachi2.core.package_managers.yarn.resolver.run_yarn_cmd")
def test_resolve_packages(mock_run_yarn_cmd: mock.Mock, rooted_tmp_path: RootedPath) -> None:
    yarn_info_output = mock_yarn_info_output(YARN_INFO_OUTPUTS)
    mock_run_yarn_cmd.return_value = yarn_info_output
    packages = resolve_packages(rooted_tmp_path)
    assert packages == EXPECT_PACKAGES

    for package in packages:
        assert package.parsed_locator == parse_locator(package.raw_locator)


@mock.patch("cachi2.core.package_managers.yarn.resolver.run_yarn_cmd")
def test_validate_unsupported_locators(
    mock_run_yarn_cmd: mock.Mock, rooted_tmp_path: RootedPath, caplog: pytest.LogCaptureFixture
) -> None:
    unsupported_outputs = [
        {
            "value": "ccto-wo-deps@git@github.com:cachito-testing/cachito-npm-without-deps.git#commit=2f0ce1d7b1f8b35572d919428b965285a69583f6",
            "children": {
                "Version": "1.0.0",
                "Cache": {
                    "Checksum": "8/3ed9ea417c75a1999925159e67cf04bf2d522967692a55321559ef2b353fa690167b7bc40e989e4ee35e36d095f007f2d0c53faeb55f14d07ec3ece34faba206",
                    "Path": "{repo_dir}/.yarn/cache/ccto-wo-deps-git@github.com-e0fce8c89c-3ed9ea417c.zip",
                    "Size": 638,
                },
            },
        },
        {
            "value": "ccto-wo-deps@patch:ccto-wo-deps@git@github.com%3Acachito-testing/cachito-npm-without-deps.git%23commit=2f0ce1d7b1f8b35572d919428b965285a69583f6#./.yarn/patches/ccto-wo-deps-git@github.com-e0fce8c89c.patch::version=1.0.0&hash=51a91f&locator=berryscary%40workspace%3A.",
            "children": {
                "Version": "1.0.0",
                "Cache": {
                    "Checksum": "8/98355f046f66b70b4ae4aec87fb20c83eb635a7138b5bb25dcbfa567ae4fcc4240ff1178de2f985776ab6cea1f55af8e085d798f5077b8a8b5bb5cb5278293d4",
                    "Path": "{repo_dir}/.yarn/cache/ccto-wo-deps-patch-c3567b709f-98355f046f.zip",
                    "Size": 647,
                },
            },
        },
        {
            "value": "holy-hand-grenade@exec:./generate-holy-hand-grenade.js#./generate-holy-hand-grenade.js::hash=3b5cbd&locator=berryscary%40workspace%3A.",
            "children": {
                "Version": "1.0.0",
                "Cache": {
                    "Checksum": "8/6053ad5dc79d8fedfdc528e1bf75e3f4a1a4558a8184f55589e1e54ab8819f5111ffc1812333906cfcfa05fdd3e81d9b65191d1a093066f3a3f479a61c626be9",
                    "Path": "{repo_dir}/.yarn/cache/holy-hand-grenade-exec-e88e9eb6dd-6053ad5dc7.zip",
                    "Size": 883,
                },
            },
        },
    ]
    yarn_info_output = mock_yarn_info_output(unsupported_outputs)
    mock_run_yarn_cmd.return_value = yarn_info_output

    with pytest.raises(
        UnsupportedFeature, match="Found 3 unsupported dependencies, more details in the logs."
    ):
        resolve_packages(rooted_tmp_path)

    assert caplog.messages == [
        "Cachi2 does not support Git or Exec dependencies for Yarn Berry: ccto-wo-deps@git@github.com:cachito-testing/cachito-npm-without-deps.git#commit=2f0ce1d7b1f8b35572d919428b965285a69583f6",
        "Cachi2 does not support Git or Exec dependencies for Yarn Berry: ccto-wo-deps@git@github.com:cachito-testing/cachito-npm-without-deps.git#commit=2f0ce1d7b1f8b35572d919428b965285a69583f6",
        "Cachi2 does not support Git or Exec dependencies for Yarn Berry: holy-hand-grenade@exec:./generate-holy-hand-grenade.js#./generate-holy-hand-grenade.js::hash=3b5cbd&locator=berryscary%40workspace%3A.",
    ]
