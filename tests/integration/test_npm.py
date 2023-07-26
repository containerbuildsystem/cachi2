import logging
from pathlib import Path
from typing import List

import pytest

from . import utils

log = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "test_params",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-bundled.git",
                ref="de68ac6aa88a81272660b6d0f6d44ce157207799",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_bundled_lockfile3",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-registry-yarnpkg.git",
                ref="f830b62780e75357c38abb7e1102871b51bfbcfe",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_lockfile3_yarn_registry",
        ),
    ],
)
def test_npm_smoketest(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    Smoketest for npm offline install development.

    :param test_params: Test case arguments
    :param tmp_path: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmp_path
    )

    utils.fetch_deps_and_check_output(
        tmp_path, test_case, test_params, source_folder, test_data_dir, cachi2_image
    )


@pytest.mark.parametrize(
    "test_params,check_cmd,expected_cmd_output",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="532dd79bde494e90fae261afbb7b464dae2d2e32",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            ["npm", "cache", "ls"],
            [
                "abbrev-2.0.0.tgz",
                "accepts-1.3.8.tgz",
                "array-flatten-1.1.1.tgz",
                "bitbucket.org/cachi-testing/cachi2-without-deps-second/cachi2-without-deps-second-external-gitcommit-09992d418fc44a2895b7a9ff27c4e32d6f74a982.tgz",
                "bitbucket.org/cachi-testing/cachi2-without-deps/cachi2-without-deps-external-gitcommit-9e164b97043a2d91bbeb992f6cc68a3d1015086a.tgz",
                "body-parser-1.20.1.tgz",
                "bytes-3.1.2.tgz",
                "call-bind-1.0.2.tgz",
                "classnames-2.3.2.tgz",
                "colors-1.4.0.tgz",
                "content-disposition-0.5.4.tgz",
                "content-type-1.0.5.tgz",
                "cookie-0.5.0.tgz",
                "cookie-signature-1.0.6.tgz",
                "csstype-3.1.2.tgz",
                "dateformat-5.0.3.tgz",
                "debug-2.6.9.tgz",
                "depd-2.0.0.tgz",
                "destroy-1.2.0.tgz",
                "ee-first-1.1.1.tgz",
                "encodeurl-1.0.2.tgz",
                "escape-html-1.0.3.tgz",
                "etag-1.8.1.tgz",
                "express-4.18.2.tgz",
                "external-cachito-npm-without-deps/cachito-npm-without-deps-external-sha512-43e71f90ad5f9eb349ab18a283f8954994def373962ddc61b866bdea4d48249e67913c6b84dca1e8c519e981ca1fcc62b438292104a88ee9ed72db76a41efede.tgz",
                "fecha-4.2.3.tgz",
                "finalhandler-1.2.0.tgz",
                "forwarded-0.2.0.tgz",
                "fresh-0.5.2.tgz",
                "function-bind-1.1.1.tgz",
                "get-intrinsic-1.2.0.tgz",
                "github.com/kevva/is-positive/is-positive-external-gitcommit-97edff6f525f192a3f83cea1944765f769ae2678.tgz",
                "has-1.0.3.tgz",
                "has-symbols-1.0.3.tgz",
                "http-errors-2.0.0.tgz",
                "iconv-lite-0.4.24.tgz",
                "inherits-2.0.4.tgz",
                "ipaddr.js-1.9.1.tgz",
                "media-typer-0.3.0.tgz",
                "merge-descriptors-1.0.1.tgz",
                "methods-1.1.2.tgz",
                "mime-1.6.0.tgz",
                "mime-db-1.52.0.tgz",
                "mime-types-2.1.35.tgz",
                "ms-2.0.0.tgz",
                "ms-2.1.3.tgz",
                "negotiator-0.6.3.tgz",
                "object-inspect-1.12.3.tgz",
                "on-finished-2.4.1.tgz",
                "parseurl-1.3.3.tgz",
                "path-to-regexp-0.1.7.tgz",
                "proxy-addr-2.0.7.tgz",
                "qs-6.11.0.tgz",
                "range-parser-1.2.1.tgz",
                "raw-body-2.5.1.tgz",
                "safe-buffer-5.2.1.tgz",
                "safer-buffer-2.1.2.tgz",
                "sax-0.1.1.tgz",
                "send-0.18.0.tgz",
                "serve-static-1.15.0.tgz",
                "setprototypeof-1.2.0.tgz",
                "side-channel-1.0.4.tgz",
                "statuses-2.0.1.tgz",
                "toidentifier-1.0.1.tgz",
                "type-is-1.6.18.tgz",
                "types-prop-types-15.7.5.tgz",
                "types-react-18.0.35.tgz",
                "types-react-dom-18.0.11.tgz",
                "types-scheduler-0.16.3.tgz",
                "unpipe-1.0.0.tgz",
                "utils-merge-1.0.1.tgz",
                "uuid-9.0.0.tgz",
                "vary-1.1.2.tgz",
            ],
            id="npm_smoketest_lockfile2",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="f1d31c2b051b218c84399b12461e0957d87bd0cd",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            ["npm", "cache", "ls"],
            [
                "abbrev-2.0.0.tgz",
                "accepts-1.3.8.tgz",
                "array-flatten-1.1.1.tgz",
                "bitbucket.org/cachi-testing/cachi2-without-deps-second/cachi2-without-deps-second-external-gitcommit-09992d418fc44a2895b7a9ff27c4e32d6f74a982.tgz",
                "bitbucket.org/cachi-testing/cachi2-without-deps/cachi2-without-deps-external-gitcommit-9e164b97043a2d91bbeb992f6cc68a3d1015086a.tgz",
                "body-parser-1.20.1.tgz",
                "bytes-3.1.2.tgz",
                "call-bind-1.0.2.tgz",
                "classnames-2.3.2.tgz",
                "colors-1.4.0.tgz",
                "content-disposition-0.5.4.tgz",
                "content-type-1.0.5.tgz",
                "cookie-0.5.0.tgz",
                "cookie-signature-1.0.6.tgz",
                "csstype-3.1.2.tgz",
                "dateformat-5.0.3.tgz",
                "debug-2.6.9.tgz",
                "depd-2.0.0.tgz",
                "destroy-1.2.0.tgz",
                "ee-first-1.1.1.tgz",
                "encodeurl-1.0.2.tgz",
                "escape-html-1.0.3.tgz",
                "etag-1.8.1.tgz",
                "express-4.18.2.tgz",
                "external-cachito-npm-without-deps/cachito-npm-without-deps-external-sha512-43e71f90ad5f9eb349ab18a283f8954994def373962ddc61b866bdea4d48249e67913c6b84dca1e8c519e981ca1fcc62b438292104a88ee9ed72db76a41efede.tgz",
                "fecha-4.2.3.tgz",
                "finalhandler-1.2.0.tgz",
                "forwarded-0.2.0.tgz",
                "fresh-0.5.2.tgz",
                "function-bind-1.1.1.tgz",
                "get-intrinsic-1.2.0.tgz",
                "github.com/kevva/is-positive/is-positive-external-gitcommit-97edff6f525f192a3f83cea1944765f769ae2678.tgz",
                "has-1.0.3.tgz",
                "has-symbols-1.0.3.tgz",
                "http-errors-2.0.0.tgz",
                "iconv-lite-0.4.24.tgz",
                "inherits-2.0.4.tgz",
                "ipaddr.js-1.9.1.tgz",
                "media-typer-0.3.0.tgz",
                "merge-descriptors-1.0.1.tgz",
                "methods-1.1.2.tgz",
                "mime-1.6.0.tgz",
                "mime-db-1.52.0.tgz",
                "mime-types-2.1.35.tgz",
                "ms-2.0.0.tgz",
                "ms-2.1.3.tgz",
                "negotiator-0.6.3.tgz",
                "object-inspect-1.12.3.tgz",
                "on-finished-2.4.1.tgz",
                "parseurl-1.3.3.tgz",
                "path-to-regexp-0.1.7.tgz",
                "proxy-addr-2.0.7.tgz",
                "qs-6.11.0.tgz",
                "range-parser-1.2.1.tgz",
                "raw-body-2.5.1.tgz",
                "safe-buffer-5.2.1.tgz",
                "safer-buffer-2.1.2.tgz",
                "sax-0.1.1.tgz",
                "send-0.18.0.tgz",
                "serve-static-1.15.0.tgz",
                "setprototypeof-1.2.0.tgz",
                "side-channel-1.0.4.tgz",
                "statuses-2.0.1.tgz",
                "toidentifier-1.0.1.tgz",
                "type-is-1.6.18.tgz",
                "types-prop-types-15.7.5.tgz",
                "types-react-18.0.35.tgz",
                "types-react-dom-18.0.11.tgz",
                "types-scheduler-0.16.3.tgz",
                "unpipe-1.0.0.tgz",
                "utils-merge-1.0.1.tgz",
                "uuid-9.0.0.tgz",
                "vary-1.1.2.tgz",
            ],
            id="npm_smoketest_lockfile3",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-npm-with-multiple-dep-versions.git",
                ref="97070a9eb06bad62eb581890731221660ade9ea3",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            ["cat", "/opt/npm-ls-output.txt"],
            [
                "/tmp/npm_lockfile3_multiple_dep_versions-source:cachito-npm-with-multiple-dep-versions@1.0.0",
                "/tmp/npm_lockfile3_multiple_dep_versions-source/node_modules/cachito-npm-without-deps:cachito-npm-without-deps@1.0.0",
                "/tmp/npm_lockfile3_multiple_dep_versions-source/node_modules/foo:foo@1.0.0:/tmp/npm_lockfile3_multiple_dep_versions-source/foo",
                "/tmp/npm_lockfile3_multiple_dep_versions-source/node_modules/is-positive:is-positive@1.0.0",
                "/tmp/npm_lockfile3_multiple_dep_versions-source/foo/node_modules/is-positive:is-positive@2.0.0",
            ],
            id="npm_lockfile3_multiple_dep_versions",
        ),
    ],
)
def test_e2e_npm(
    test_params: utils.TestParameters,
    check_cmd: List[str],
    expected_cmd_output: str,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    End to end test for npm.

    :param test_params: Test case arguments
    :param tmp_path: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmp_path
    )

    output_folder = utils.fetch_deps_and_check_output(
        tmp_path, test_case, test_params, source_folder, test_data_dir, cachi2_image
    )

    utils.build_image_and_check_cmd(
        tmp_path,
        output_folder,
        test_data_dir,
        test_case,
        check_cmd,
        expected_cmd_output,
        cachi2_image,
    )
