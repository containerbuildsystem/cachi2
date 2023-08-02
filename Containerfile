FROM registry.fedoraproject.org/fedora-minimal:38
LABEL maintainer="Red Hat"

WORKDIR /src
RUN microdnf -y install \
    --setopt install_weak_deps=0 \
    --nodocs \
    golang \
    git-core \
    python3 \
    python3-pip \
    && microdnf clean all

COPY . .

RUN pip3 install -r requirements.txt --no-deps --no-cache-dir --require-hashes && \
    pip3 install --no-cache-dir -e . && \
    # the git folder is only needed to determine the package version
    rm -rf .git

ENTRYPOINT ["cachi2"]
