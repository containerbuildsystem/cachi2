#!/bin/bash
set -o errexit -o nounset -o pipefail

cat << banner-end
--------------------------------------------------------------------------------
Generating mock data for gomod unit tests
--------------------------------------------------------------------------------
banner-end

mocked_data_dir=${1:-tests/unit/data/gomod-mocks}
mkdir -p "$mocked_data_dir/non-vendored"
mkdir -p "$mocked_data_dir/vendored"
mocked_data_dir_abspath=$(realpath "$mocked_data_dir")

tmpdir=$(dirname "$(mktemp --dry-run)")

git clone https://github.com/cachito-testing/gomod-pandemonium \
    "$tmpdir/gomod-pandemonium"
trap 'rm -rf "$tmpdir/gomod-pandemonium"' EXIT

cat << banner-end
--------------------------------------------------------------------------------
$(
    # cd in a subshell, doesn't change the $PWD of the main process
    cd "$tmpdir/gomod-pandemonium"
    export GOMODCACHE="$tmpdir/cachi2-mock-gomodcache"

    echo "generating $mocked_data_dir/non-vendored/go_mod_download.json"
    go mod download -json > \
        "$mocked_data_dir_abspath/non-vendored/go_mod_download.json"

    echo "generating $mocked_data_dir/non-vendored/go_list_deps_all.json"
    go list -deps -json=ImportPath,Module,Standard,Deps all > \
        "$mocked_data_dir_abspath/non-vendored/go_list_deps_all.json"

    echo "generating $mocked_data_dir/non-vendored/go_list_deps_threedot.json"
    go list -deps -json=ImportPath,Module,Standard,Deps ./... > \
        "$mocked_data_dir_abspath/non-vendored/go_list_deps_threedot.json"

    echo "generating $mocked_data_dir/vendored/modules.txt"
    go mod vendor
    cp vendor/modules.txt "$mocked_data_dir_abspath/vendored/modules.txt"

    echo "generating $mocked_data_dir/vendored/go_list_deps_all.json"
    go list -deps -json=ImportPath,Module,Standard,Deps all > \
        "$mocked_data_dir_abspath/vendored/go_list_deps_all.json"

    echo "generating $mocked_data_dir/vendored/go_list_deps_threedot.json"
    go list -deps -json=ImportPath,Module,Standard,Deps ./... > \
        "$mocked_data_dir_abspath/vendored/go_list_deps_threedot.json"
)
--------------------------------------------------------------------------------
banner-end

find "$mocked_data_dir/non-vendored" "$mocked_data_dir/vendored" -type f |
    while read -r f; do
        sed "s|$tmpdir.cachi2-mock-gomodcache|{gomodcache_dir}|" --in-place "$f"
        sed "s|$tmpdir.gomod-pandemonium|{repo_dir}|" --in-place "$f"
    done

nonvendor_changed=$(git diff -- "$mocked_data_dir/non-vendored")
vendor_changed=$(git diff -- "$mocked_data_dir/vendored")

if [[ -n "$vendor_changed" || -n "$nonvendor_changed" ]]; then
    cat << banner-end
The mock data changed => the expected unit test results may change.
The following files may need to be adjusted manually:
$(
    if [[ -n "$nonvendor_changed" ]]; then
        echo "  $mocked_data_dir/expected-results/resolve_gomod.json"
    fi
    if [[ -n "$vendor_changed" ]]; then
        echo "  $mocked_data_dir/expected-results/resolve_gomod_vendored.json"
    fi
)
--------------------------------------------------------------------------------
banner-end
fi
