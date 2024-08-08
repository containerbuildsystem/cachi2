#!/bin/bash
set -e

# setup dir
mkdir /dnfrepo
chown root:nginx /dnfrepo 
chmod 770 /dnfrepo

# download  an RPM
dnf download --downloaddir /dnfrepo nano

# run createrepo
createrepo_c /dnfrepo

