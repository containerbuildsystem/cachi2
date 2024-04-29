FROM registry.fedoraproject.org/fedora-minimal:39
LABEL maintainer="Red Hat"

WORKDIR /src
RUN microdnf -y install \
    --setopt install_weak_deps=0 \
    --nodocs \
    gcc \
    golang \
    git-core \
    nodejs \
    nodejs-npm \
    python3 \
    python3-devel \
    python3-pip \
    && microdnf clean all

COPY . .

RUN pip3 install -r requirements.txt --no-deps --no-cache-dir --require-hashes && \
    pip3 install --no-cache-dir . && \
    # the git folder is only needed to determine the package version
    rm -rf .git

WORKDIR /src/js-deps
RUN npm install && \
    ln -s "${PWD}/node_modules/.bin/corepack" /usr/local/bin/corepack && \
    corepack enable yarn && \
    microdnf -y remove nodejs-npm

# Manual install of specific fixed Go SDK versions (1.20 & 1.21.0):
#   - install Go's official shim
#   - let the shim download the actual Go SDK (the download forces the output parent dir to $HOME)
#   - move the SDK to a host local install system-wide location
#   - remove the shim as it forces and expects the SDK to be used from $HOME
#   - clean any build artifacts Go creates as part of the process.
RUN for go_ver in "go1.20" "go1.21.0"; do \
        go install "golang.org/dl/${go_ver}@latest" && \
        "$HOME/go/bin/$go_ver" download && \
        mkdir -p /usr/local/go && \
        mv "$HOME/sdk/$go_ver" /usr/local/go && \
        rm -rf "$HOME/go" "$HOME/.cache/go-build/"; \
    done

ENTRYPOINT ["cachi2"]
