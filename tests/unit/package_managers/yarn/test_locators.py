import pytest

from cachi2.core.errors import UnexpectedFormat
from cachi2.core.package_managers.yarn.locators import (
    _parse_locator,
    _parse_reference,
    _ParsedLocator,
    _ParsedReference,
)

SUPPORTED_LOCATORS = [
    # scoped registry deps
    "@isaacs/cliui@npm:8.0.2",
    "@npmcli/fs@npm:3.1.0",
    # unscoped registry deps
    "abbrev@npm:1.1.1",
    "agent-base@npm:6.0.2",
    # workspaces
    "@montypython/brian@workspace:packages/the-life-of/brian",
    "the-answer@workspace:packages/the-answer",
    # file-like deps
    "ansi-regex-link@link:external-packages/ansi-regex::locator=berryscary%40workspace%3A.",
    "once-portal@portal:external-packages/once::locator=berryscary%40workspace%3A.",
    "supports-hyperlinks-folder@file:external-packages/supports-hyperlinks#external-packages/supports-hyperlinks::hash=cfa5f5&locator=berryscary%40workspace%3A.",
    "strip-ansi-tarball@file:../../external-packages/strip-ansi-4.0.0.tgz::locator=the-answer%40workspace%3Apackages%2Fthe-answer",
    "strip-ansi-tarball@file:external-packages/strip-ansi-4.0.0.tgz::locator=berryscary%40workspace%3A.",
    # https dep
    "c2-wo-deps-2@https://bitbucket.org/cachi-testing/cachi2-without-deps-second/get/09992d418fc44a2895b7a9ff27c4e32d6f74a982.tar.gz",
    # optional custom patch for a registry dep
    "left-pad@npm:1.3.0",
    "left-pad@patch:left-pad@npm%3A1.3.0#~./my-patches/left-pad.patch::version=1.3.0&hash=629bda&locator=berryscary%40workspace%3A.",
    # optional builtin patch
    "fsevents@npm:2.3.2",
    "fsevents@patch:fsevents@npm%3A2.3.2#~builtin<compat/fsevents>::version=2.3.2&hash=df0bf1",
    # non-optional builtin patch (in reality, the typescript patch is optional)
    "typescript@npm:5.1.6",
    "typescript@patch:typescript@npm%3A5.1.6#builtin<compat/typescript>::version=5.1.6&hash=5da071",
    # multiple patches of all kinds
    "is-positive@npm:3.1.0",
    "is-negative@patch:is-positive@npm%3A3.1.0#~builtin<foo>&./my-patches/is-positive.patch&builtin<bar>&~./baz.patch::version=3.1.0&locator=berryscary%40workspace%3A.",
]

UNSUPPORTED_LOCATORS = [
    # exec dep
    "holy-hand-grenade@exec:./generate-holy-hand-grenade.js#./generate-holy-hand-grenade.js::hash=3b5cbd&locator=berryscary%40workspace%3A.",
    # git deps
    "c2-wo-deps@https://bitbucket.org/cachi-testing/cachi2-without-deps.git#commit=9e164b97043a2d91bbeb992f6cc68a3d1015086a",
    "ccto-wo-deps@git@github.com:cachito-testing/cachito-npm-without-deps.git#commit=2f0ce1d7b1f8b35572d919428b965285a69583f6",
    # specific workspace of a git dep
    "npm-lifecycle-scripts@https://github.com/chmeliik/js-lifecycle-scripts.git#workspace=my-workspace&commit=0e786c88d5aca79a68428dadaed4b096bf2ae3e0",
    # patched git dep
    "ccto-wo-deps@patch:ccto-wo-deps@git@github.com%3Acachito-testing/cachito-npm-without-deps.git%23commit=2f0ce1d7b1f8b35572d919428b965285a69583f6#./.yarn/patches/ccto-wo-deps-git@github.com-e0fce8c89c.patch::version=1.0.0&hash=51a91f&locator=berryscary%40workspace%3A.",
]

ALL_LOCATORS = SUPPORTED_LOCATORS + UNSUPPORTED_LOCATORS

PARSED_LOCATORS_AND_REFERENCES = [
    (
        _ParsedLocator(scope="isaacs", name="cliui", raw_reference="npm:8.0.2"),
        _ParsedReference(protocol="npm:", source=None, selector="8.0.2", params=None),
    ),
    (
        _ParsedLocator(scope="npmcli", name="fs", raw_reference="npm:3.1.0"),
        _ParsedReference(protocol="npm:", source=None, selector="3.1.0", params=None),
    ),
    (
        _ParsedLocator(scope=None, name="abbrev", raw_reference="npm:1.1.1"),
        _ParsedReference(protocol="npm:", source=None, selector="1.1.1", params=None),
    ),
    (
        _ParsedLocator(scope=None, name="agent-base", raw_reference="npm:6.0.2"),
        _ParsedReference(protocol="npm:", source=None, selector="6.0.2", params=None),
    ),
    (
        _ParsedLocator(
            scope="montypython", name="brian", raw_reference="workspace:packages/the-life-of/brian"
        ),
        _ParsedReference(
            protocol="workspace:", source=None, selector="packages/the-life-of/brian", params=None
        ),
    ),
    (
        _ParsedLocator(
            scope=None, name="the-answer", raw_reference="workspace:packages/the-answer"
        ),
        _ParsedReference(
            protocol="workspace:", source=None, selector="packages/the-answer", params=None
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="ansi-regex-link",
            raw_reference="link:external-packages/ansi-regex::locator=berryscary%40workspace%3A.",
        ),
        _ParsedReference(
            protocol="link:",
            source=None,
            selector="external-packages/ansi-regex",
            params={"locator": ["berryscary@workspace:."]},
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="once-portal",
            raw_reference="portal:external-packages/once::locator=berryscary%40workspace%3A.",
        ),
        _ParsedReference(
            protocol="portal:",
            source=None,
            selector="external-packages/once",
            params={"locator": ["berryscary@workspace:."]},
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="supports-hyperlinks-folder",
            raw_reference="file:external-packages/supports-hyperlinks#external-packages/supports-hyperlinks::hash=cfa5f5&locator=berryscary%40workspace%3A.",
        ),
        _ParsedReference(
            protocol="file:",
            source="external-packages/supports-hyperlinks",
            selector="external-packages/supports-hyperlinks",
            params={"hash": ["cfa5f5"], "locator": ["berryscary@workspace:."]},
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="strip-ansi-tarball",
            raw_reference="file:../../external-packages/strip-ansi-4.0.0.tgz::locator=the-answer%40workspace%3Apackages%2Fthe-answer",
        ),
        _ParsedReference(
            protocol="file:",
            source=None,
            selector="../../external-packages/strip-ansi-4.0.0.tgz",
            params={"locator": ["the-answer@workspace:packages/the-answer"]},
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="strip-ansi-tarball",
            raw_reference="file:external-packages/strip-ansi-4.0.0.tgz::locator=berryscary%40workspace%3A.",
        ),
        _ParsedReference(
            protocol="file:",
            source=None,
            selector="external-packages/strip-ansi-4.0.0.tgz",
            params={"locator": ["berryscary@workspace:."]},
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="c2-wo-deps-2",
            raw_reference="https://bitbucket.org/cachi-testing/cachi2-without-deps-second/get/09992d418fc44a2895b7a9ff27c4e32d6f74a982.tar.gz",
        ),
        _ParsedReference(
            protocol="https:",
            source=None,
            selector="//bitbucket.org/cachi-testing/cachi2-without-deps-second/get/09992d418fc44a2895b7a9ff27c4e32d6f74a982.tar.gz",
            params=None,
        ),
    ),
    (
        _ParsedLocator(scope=None, name="left-pad", raw_reference="npm:1.3.0"),
        _ParsedReference(protocol="npm:", source=None, selector="1.3.0", params=None),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="left-pad",
            raw_reference="patch:left-pad@npm%3A1.3.0#~./my-patches/left-pad.patch::version=1.3.0&hash=629bda&locator=berryscary%40workspace%3A.",
        ),
        _ParsedReference(
            protocol="patch:",
            source="left-pad@npm:1.3.0",
            selector="~./my-patches/left-pad.patch",
            params={
                "version": ["1.3.0"],
                "hash": ["629bda"],
                "locator": ["berryscary@workspace:."],
            },
        ),
    ),
    (
        _ParsedLocator(scope=None, name="fsevents", raw_reference="npm:2.3.2"),
        _ParsedReference(protocol="npm:", source=None, selector="2.3.2", params=None),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="fsevents",
            raw_reference="patch:fsevents@npm%3A2.3.2#~builtin<compat/fsevents>::version=2.3.2&hash=df0bf1",
        ),
        _ParsedReference(
            protocol="patch:",
            source="fsevents@npm:2.3.2",
            selector="~builtin<compat/fsevents>",
            params={"version": ["2.3.2"], "hash": ["df0bf1"]},
        ),
    ),
    (
        _ParsedLocator(scope=None, name="typescript", raw_reference="npm:5.1.6"),
        _ParsedReference(protocol="npm:", source=None, selector="5.1.6", params=None),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="typescript",
            raw_reference="patch:typescript@npm%3A5.1.6#builtin<compat/typescript>::version=5.1.6&hash=5da071",
        ),
        _ParsedReference(
            protocol="patch:",
            source="typescript@npm:5.1.6",
            selector="builtin<compat/typescript>",
            params={"version": ["5.1.6"], "hash": ["5da071"]},
        ),
    ),
    (
        _ParsedLocator(scope=None, name="is-positive", raw_reference="npm:3.1.0"),
        _ParsedReference(protocol="npm:", source=None, selector="3.1.0", params=None),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="is-negative",
            raw_reference="patch:is-positive@npm%3A3.1.0#~builtin<foo>&./my-patches/is-positive.patch&builtin<bar>&~./baz.patch::version=3.1.0&locator=berryscary%40workspace%3A.",
        ),
        _ParsedReference(
            protocol="patch:",
            source="is-positive@npm:3.1.0",
            selector="~builtin<foo>&./my-patches/is-positive.patch&builtin<bar>&~./baz.patch",
            params={"version": ["3.1.0"], "locator": ["berryscary@workspace:."]},
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="holy-hand-grenade",
            raw_reference="exec:./generate-holy-hand-grenade.js#./generate-holy-hand-grenade.js::hash=3b5cbd&locator=berryscary%40workspace%3A.",
        ),
        _ParsedReference(
            protocol="exec:",
            source="./generate-holy-hand-grenade.js",
            selector="./generate-holy-hand-grenade.js",
            params={"hash": ["3b5cbd"], "locator": ["berryscary@workspace:."]},
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="c2-wo-deps",
            raw_reference="https://bitbucket.org/cachi-testing/cachi2-without-deps.git#commit=9e164b97043a2d91bbeb992f6cc68a3d1015086a",
        ),
        _ParsedReference(
            protocol="https:",
            source="//bitbucket.org/cachi-testing/cachi2-without-deps.git",
            selector="commit=9e164b97043a2d91bbeb992f6cc68a3d1015086a",
            params=None,
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="ccto-wo-deps",
            raw_reference="git@github.com:cachito-testing/cachito-npm-without-deps.git#commit=2f0ce1d7b1f8b35572d919428b965285a69583f6",
        ),
        _ParsedReference(
            protocol="git@github.com:",
            source="cachito-testing/cachito-npm-without-deps.git",
            selector="commit=2f0ce1d7b1f8b35572d919428b965285a69583f6",
            params=None,
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="npm-lifecycle-scripts",
            raw_reference="https://github.com/chmeliik/js-lifecycle-scripts.git#workspace=my-workspace&commit=0e786c88d5aca79a68428dadaed4b096bf2ae3e0",
        ),
        _ParsedReference(
            protocol="https:",
            source="//github.com/chmeliik/js-lifecycle-scripts.git",
            selector="workspace=my-workspace&commit=0e786c88d5aca79a68428dadaed4b096bf2ae3e0",
            params=None,
        ),
    ),
    (
        _ParsedLocator(
            scope=None,
            name="ccto-wo-deps",
            raw_reference="patch:ccto-wo-deps@git@github.com%3Acachito-testing/cachito-npm-without-deps.git%23commit=2f0ce1d7b1f8b35572d919428b965285a69583f6#./.yarn/patches/ccto-wo-deps-git@github.com-e0fce8c89c.patch::version=1.0.0&hash=51a91f&locator=berryscary%40workspace%3A.",
        ),
        _ParsedReference(
            protocol="patch:",
            source="ccto-wo-deps@git@github.com:cachito-testing/cachito-npm-without-deps.git#commit=2f0ce1d7b1f8b35572d919428b965285a69583f6",
            selector="./.yarn/patches/ccto-wo-deps-git@github.com-e0fce8c89c.patch",
            params={
                "version": ["1.0.0"],
                "hash": ["51a91f"],
                "locator": ["berryscary@workspace:."],
            },
        ),
    ),
]


@pytest.mark.parametrize(
    "locator_str, expect_parsed_locator, expect_parsed_reference",
    [
        (locator_str, parsed_locator, parsed_reference)
        for locator_str, (parsed_locator, parsed_reference) in zip(
            ALL_LOCATORS, PARSED_LOCATORS_AND_REFERENCES
        )
    ],
)
def test_parse_locator_helper(
    locator_str: str,
    expect_parsed_locator: _ParsedLocator,
    expect_parsed_reference: _ParsedReference,
) -> None:
    """Test the helpers that parse locators and references generically.

    Note that these don't care which locator types are supported and which aren't.
    """
    locator = _parse_locator(locator_str)
    assert locator == expect_parsed_locator
    assert locator.parsed_reference == expect_parsed_reference
    assert str(locator) == locator_str


@pytest.mark.parametrize(
    "locator_str",
    [
        "name",
        "@scope/name",
        "name@",
        "@scope/name@",
        "@reference",
        "@scope@reference",
        "@scope/@reference",
        "name/@reference",
    ],
)
def test_unexpected_locator_format(locator_str: str) -> None:
    with pytest.raises(UnexpectedFormat, match="could not parse locator"):
        _parse_locator(locator_str)


def test_unexpected_reference_format() -> None:
    with pytest.raises(UnexpectedFormat, match="could not parse reference"):
        # it is very difficult to find something that doesn't match, probably not doable without \n
        # kudos to hypothesis: https://hypothesis.readthedocs.io/en/latest/index.html
        # ^<empty protocol>:<no source><empty selector>::<empty params>$ - and 'x' is left unmatched
        _parse_reference(":::\nx")
