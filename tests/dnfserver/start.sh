#!/bin/bash
set -o errexit -o nounset -o pipefail

DIR=$(dirname "$(realpath "${BASH_SOURCE[0]}")")

# build image here
podman build -t localhost/dnfserver .

DEFAULT_IMAGE=localhost/dnfserver
DEFAULT_PORT=8443

cleanup() {
    rm -r "$WORKDIR" || true
    # podman volume rm -f --time 0 cachi2-dnfserver-packages >/dev/null || true
    # podman volume rm -f --time 0 cachi2-dnfserver-auth >/dev/null || true
    podman rmi -f localhost/dnfserver
}

WORKDIR=$(mktemp -d --tmpdir "cachi2-dnfserver.XXXXXX")
trap cleanup EXIT

setup() {
    #echo -e "\n--- Downloading $DIR/package-urls.txt ---\n"

    #mkdir "$WORKDIR/packages"
    #sed '/^#/d' "$DIR/package-urls.txt" |
    #    xargs curl --fail --remote-name-all --output-dir "$WORKDIR/packages"

    #echo -e "\n--- Setting cachi2-user:cachi2-pass authentication ---\n"

    mkdir "$WORKDIR/certs"
    # Content based on htpasswd -b -c .htpasswd cachi2-user cachi2-pass; cat .htpasswd
    # shellcheck disable=SC2016
    #echo 'cachi2-user:$apr1$ChHgbvcg$l1QSrRehMhD0XOjj9ruem/' > "$WORKDIR/auth/.htpasswd"

    #echo -e "\n--- Creating podman volumes ---\n"

    # Note: it's not strictly necessary to create these volumes, we could mount the content
    # straight from the $WORKDIR. But pypiserver chowns the packages, making it impossible
    # for this script to fully clean up after itself. Using podman volumes avoids that.

    #echo "Importing content of $WORKDIR/packages: cachi2-pypiserver-packages"
    #podman volume create --ignore cachi2-pypiserver-packages >/dev/null
    #ls -lA "$WORKDIR/packages"
    #tar cf - -C "$WORKDIR/packages" . | podman volume import cachi2-pypiserver-packages -

    #echo "Importing content of $WORKDIR/auth: cachi2-pypiserver-auth"
    #podman volume create --ignore cachi2-pypiserver-auth >/dev/null
    #ls -lA "$WORKDIR/auth"
    #tar cf - -C "$WORKDIR/auth" . | podman volume import cachi2-pypiserver-auth -

    echo -e "\n--- Starting dnfserver on http://localhost:${DNFSERVER_PORT:-8080} ---\n"
}

setup >&2

podman run --rm --replace --name cachi2-dnfserver \
    -p "${DNFSERVER_PORT:-$DEFAULT_PORT}":443 \
    "${DNFSERVER_IMAGE:-$DEFAULT_IMAGE}"