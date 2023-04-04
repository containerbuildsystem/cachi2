FROM registry.fedoraproject.org/fedora-minimal:37
LABEL name="Cachi2" \
      vendor="RHTAP Build Team" \
      maintainer="container-build-guild@redhat.com" \
      release="1" \
      build-date=$BUILD_DATE \
      description="CLI tool for prefetching build dependencies" \
      url="https://github.com/containerbuildsystem/cachi2" \
      distribution-scope="public" \
      io.k8s.description="CLI tool for prefetching build dependencies" \
      io.k8s.display-name="Cachi2" \
      vcs-ref=$GIT_ID \
      vcs-type=git \
      architecture=$TARGETARCH \
      com.redhat.component="rhtap-build-cachi2"

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
