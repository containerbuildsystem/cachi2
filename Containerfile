# hadolint global ignore=DL3007

########################
# PREPARE OUR BASE IMAGE
########################
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest as base
RUN microdnf -y install \
    --setopt install_weak_deps=0 \
    --nodocs \
    git-core \
    nodejs \
    python3 \
    && microdnf clean all

######################
# BUILD/INSTALL CACHI2
######################
FROM base as builder
WORKDIR /src
COPY . .
RUN microdnf -y install \
    --setopt install_weak_deps=0 \
    --nodocs \
    gcc \
    golang-bin \
    nodejs \
    npm \
    python3-devel \
    python3-pip \
    python3-setuptools \
    && microdnf clean all

RUN python3 -m venv /venv && \
    /venv/bin/pip install -r requirements.txt --no-deps --no-cache-dir --require-hashes && \
    /venv/bin/pip install --no-cache-dir .

##########################
# ASSEMBLE THE FINAL IMAGE
##########################
FROM base
LABEL maintainer="Red Hat"

# copy Go SDKs from official Debian images, corepack from official Node.js Alpine
COPY --from=docker.io/library/golang:1.20.0-bullseye /usr/local/go /usr/local/go/go1.20
COPY --from=docker.io/library/golang:1.21.0-bullseye /usr/local/go /usr/local/go/go1.21
COPY --from=docker.io/library/node:21-alpine /usr/local/lib/node_modules/corepack /usr/local/lib/corepack
COPY --from=builder /venv /venv

# link corepack, yarn, and go to standard PATH location
RUN ln -s /usr/local/lib/corepack/dist/corepack.js /usr/local/bin/corepack && \
    ln -s /usr/local/lib/corepack/dist/yarn.js /usr/local/bin/yarn && \
    ln -s /usr/local/go/go1.21/bin/go /usr/local/bin/go && \
    ln -s /venv/bin/cachi2 /usr/local/bin/cachi2

ENTRYPOINT ["/usr/local/bin/cachi2"]
