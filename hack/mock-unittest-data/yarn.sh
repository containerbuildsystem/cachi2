#!/bin/bash
set -o errexit -o nounset -o pipefail

cat << banner-end
--------------------------------------------------------------------------------
Generating mock data for yarn unit tests
--------------------------------------------------------------------------------
banner-end

tmpdir=$(dirname "$(mktemp --dry-run)")

git clone https://github.com/cachito-testing/cachi2-yarn-berry \
    --depth=1 \
    --single-branch \
    --branch=zero-installs \
    "$tmpdir/cachi2-yarn-berry"
trap 'rm -rf "$tmpdir/cachi2-yarn-berry"' EXIT

cd "$tmpdir/cachi2-yarn-berry"

yarn info --all --recursive --cache --json |
    # filter out unsupported protocols
    jq 'select(.value | test("commit=") | not)' > yarninfo.json

# - take 1 or 2 examples of each supported protocol
# - make sure to include the curious case where
#   checksum is null but path isn't
jq -s < yarninfo.json '
    map(select(.value | test("@npm:")))[0],
    map(select(.value | test("@workspace:")))[0,1],
    map(select(.value | test("@patch:")))[0,1],
    map(select(.value | test("@file:")))[0,1],
    map(select(.value | test("@portal:")))[0],
    map(select(.value | test("@link:")))[0],
    map(select(.value | test("@https:.*tar.gz")))[0],
    map(select(.children.Cache | (.Checksum == null) and (.Path != null)))[]
' |
    # make unique by locator, drop large unused Dependencies attribute
    jq --compact-output -s '
        unique_by(.value)[]
        | del(.children.Dependencies)
    ' |
    sed "s;$PWD;{repo_dir};" |
    python -c '
import json, pprint, sys

pprint.pprint(list(map(json.loads, sys.stdin)), sort_dicts=False)
' > yarninfo.py

cat << banner-end
--------------------------------------------------------------------------------
You can copy the following to tests/unit/package_managers/yarn/test_resolver.py
(you will need to re-format it with 'black')
--------------------------------------------------------------------------------
banner-end

cat yarninfo.py
