# Usage

Examples:

* For [Go modules](#example-go-modules) (most complete explanation)
* For [pip](#example-pip)

General process:

1. [pre-fetch dependencies](#pre-fetch-dependencies)
2. [generate environment variables](#generate-environment-variables)
3. [inject project files](#inject-project-files)
4. set the environment variables ([Containerfile example](#write-the-dockerfile-or-containerfile))
5. run the build ([container build example](#build-the-container))

## Example: Go modules

Let's show Cachi2 usage by building the glorious [fzf](https://github.com/junegunn/fzf) CLI tool hermetically. To follow
along, clone the repository to your local disk.

```shell
git clone https://github.com/junegunn/fzf --branch=0.34.0
```

The best way to run `cachi2` is via the [container image](../README.md#container-image).

### Pre-fetch dependencies

```shell
cachi2 fetch-deps \
  --source ./fzf \
  --output ./cachi2-output \
  '{"path": ".", "type": "gomod"}'
```

* `--source` - the path to a *git repository* on the local disk
* `--output` - the path to the directory where Cachi2 will write all output
* `{JSON}`   - specifies a *package* (a directory) within the repository to process

Note that Cachi2 does not auto-detect which package managers your project uses. You need to tell Cachi2 what to process
when calling fetch-deps. In the example above, the package is a go module located at the root of the fzf repo,
hence the relative path is `.`.

The main parameter (PKG) can handle different types of definitions:

* simple: `gomod`, same as `{"path": ".", "type": "gomod"}`
* JSON object: `{"path": "subpath/to/other/module", "type": "gomod"}`
* JSON array: `[{"path": ".", "type": "gomod"}, {"path": "subpath/to/other/module", "type": "gomod"}]`
* JSON object with flags:
`{"packages": [{"path": ".", "type": "gomod"}], "flags": ["gomod-vendor"]}`

See also `cachi2 fetch-deps --help`.

### Generate environment variables

```shell
cachi2 generate-env ./cachi2-output -o ./cachi2.env --for-output-dir /tmp/cachi2-output
```

```shell
$ cat cachi2.env
export GOCACHE=/tmp/cachi2-output/deps/gomod
export GOMODCACHE=/tmp/cachi2-output/deps/gomod/pkg/mod
export GOPATH=/tmp/cachi2-output/deps/gomod
export GOSUMDB=off
```

To make use of the pre-fetched dependencies, you need to tell your package manager where to find them. This often
involves setting environment variables, for example to point to a cache directory.

Cachi2 provides a helper command to generate the environment variables in an easy-to-use format. The example above
uses the "env" format which generates a simple shell script that `export`s the required variables (properly shell quoted
when necessary). You can `source` this file to set the variables.

Don't worry about the `--for-output-dir` option yet - and about the fact that the directory does not exist - it has to
do with the target path where we will mount the output directory [during the build](#build-the-container).

See also `cachi2 generate-env --help`.

### Inject project files

```shell
cachi2 inject-files ./cachi2-output --for-output-dir /tmp/cachi2-output
```

*⚠ Cachi2 may overwrite existing files. Please make sure you have no un-committed changes (that you are not prepared to
lose) when calling inject-files.*

For some package managers, to use the pre-fetched dependencies you may need to create a configuration file or edit
a lockfile (or some other file in your project directory).

Before starting your build, call `cachi2 inject-files` to automatically make the necessary changes in your repo (based
on data in the fetch-deps output directory). Please do not change the absolute path to the repo between the calls to
fetch-deps and inject-files; if it's not at the same path, the inject-files command won't find it.

The `--for-output-dir` option has the same meaning as the one used when generating environment variables.

### Write the Dockerfile (or Containerfile)

```dockerfile
FROM golang:1.19.2-alpine3.16 AS build

COPY ./fzf /src/fzf
WORKDIR /src/fzf

RUN source /tmp/cachi2.env && \
    go build -o /fzf

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.0.0

COPY --from=build /fzf /usr/bin/fzf

CMD ls | fzf
```

The part where we `source` the environment file is Cachi2-specific - the rest of the container build is business as
usual for a golang project. See the next section if you are wondering how the file will get there.

⚠ The `source`d environment variables do not persist to the next RUN instruction. The sourcing of the file and the
package manager command(s) need to be in the same instruction. If the build needs more than one command and you would
like to split them into separate RUN instructions, `source` the environment file in each one.

```dockerfile
RUN source /tmp/cachi2.env && \
    go build -o /foo cmd/foo && \
    go build -o /bar cmd/bar

# or, if preferrable
RUN source /tmp/cachi2.env && go build -o /foo cmd/foo
RUN source /tmp/cachi2.env && go build -o /bar cmd/bar
```

### Build the container

```shell
podman build . \
  --volume "$(realpath ./cachi2-output)":/tmp/cachi2-output:Z \
  --volume "$(realpath ./cachi2.env)":/tmp/cachi2.env:Z \
  --network none \
  --tag fzf

# test that it worked
podman run --rm -ti fzf
```

We use the `--volume` option to mount Cachi2 resources into the container build - the output directory at
/tmp/cachi2-output/ and the environment file at /tmp/cachi2.env.

The path where the output directory gets mounted is important. Some environment variables or project files may use
absolute paths to content in the output directory; if the directory is not at the expected path, the paths will be
wrong. Remember the `--for-output-dir` option used when [generating the env file](#generate-environment-variables)
and [injecting the project files](#inject-project-files)? The absolute path to ./cachi2-output on your machine is
(probably) not /tmp/cachi2-output. That is why we had to tell the generate-env command what the path inside the
container is eventually going to be.

As for the network-isolation part, we solve it by using the `--network=none` option. Note that this option only works
if your podman/buildah version contains the fix for [buildah#4227](https://github.com/containers/buildah/issues/4227)
(buildah >= 1.28). In older versions, a workaround could be to manually create an internal network (but you'll need root
privileges): `sudo podman network create --internal isolated-network; sudo podman build --network isolated-network ...`.

## Example: pip

Let's build [atomic-reactor](https://github.com/containerbuildsystem/atomic-reactor). Atomic-reactor already builds
with Cachito (Cachi2's spiritual ancestor), which makes it a rare example of a Python project that meets Cachi2's
requirements out of the box (see [pip.md](pip.md) for more context).

Get the repo if you want to try for yourself:

```shell
git clone https://github.com/containerbuildsystem/atomic-reactor --branch=4.4.0
```

### Pre-fetch dependencies (pip)

```shell
cachi2 fetch-deps --source ./atomic-reactor '{
  "type": "pip",
  "requirements_files": ["requirements.txt"],
  "requirements_build_files": ["requirements-build.txt", "requirements-pip.txt"]
}'
```

Details: [pre-fetch dependencies](#pre-fetch-dependencies)

### Generate environment variables (pip)

```shell
cachi2 generate-env ./cachi2-output -o ./cachi2.env --for-output-dir /tmp/cachi2-output
```

```shell
$ cat cachi2.env
export PIP_FIND_LINKS=/tmp/cachi2-output/deps/pip
export PIP_NO_INDEX=true
```

Details: [generate environment variables](#generate-environment-variables)

### Inject project files (pip)

```shell
$ cachi2 inject-files ./cachi2-output --for-output-dir /tmp/cachi2-output
2023-01-26 16:41:09,990 INFO Overwriting /tmp/test/atomic-reactor/requirements.txt
```

The relevant part of the diff:

```diff
diff --git a/requirements.txt b/requirements.txt
-osbs-client @ git+https://github.com/containerbuildsystem/osbs-client@8d7d7fadff38c8367796e6ac0b3516b65483db24
-    # via -r requirements.in
+osbs-client @ file:///tmp/cachi2-output/deps/pip/github.com/containerbuildsystem/osbs-client/osbs-client-external-gitcommit-8d7d7fadff38c8367796e6ac0b3516b65483db24.tar.gz
```

Details: [inject project files](#inject-project-files)

### Build the base image (pip)

For this example, we will split the build into two parts - a base image and the final application image. In the base
image build, we will cheat a bit and install "devel" libraries from RPMs. That means we won't be able to use network
isolation (need to download the RPMs).

If your project doesn't need to compile as many C packages as atomic-reactor, you may be able to find a base image that
already contains everything you need.

Containerfile.baseimage:

```Dockerfile
FROM quay.io/centos/centos:stream8

# python3.8 runtime, C build dependencies
RUN dnf -y install \
        python38 \
        python38-pip \
        python38-devel \
        gcc \
        make \
        libffi-devel \
        krb5-devel \
        cairo-devel \
        cairo-gobject-devel \
        gobject-introspection-devel \
        openssl-devel && \
    dnf clean all
```

Build the image:

```shell
podman build . -f Containerfile.baseimage --tag atomic-reactor-base-image:latest
```

### Build the application image (pip)

We will base the final application image on our custom base image. The base image build installed all the RPMs we will
need, so the final phase can use network isolation again 🎉.

Containerfile:

```Dockerfile
FROM atomic-reactor-base-image:latest

COPY atomic-reactor/ /src/atomic-reactor
WORKDIR /src/atomic-reactor

# Need to source the cachi2.env file to set the environment variables
# (in the same RUN instruction as the pip commands)
RUN source /tmp/cachi2.env && \
    # We're using network isolation => cannot build the cryptography package with Rust
    # (it downloads Rust crates)
    export CRYPTOGRAPHY_DONT_BUILD_RUST=1 && \
    python3.8 -m pip install -U pip && \
    python3.8 -m pip install --use-pep517 -r requirements.txt && \
    python3.8 -m pip install --use-pep517 .

CMD ["python3.8", "-m", "atomic_reactor.cli.main", "--help"]
```

Build the image:

```shell
podman build . \
  --volume "$(realpath ./cachi2-output)":/tmp/cachi2-output:Z \
  --volume "$(realpath ./cachi2.env)":/tmp/cachi2.env:Z \
  --network none \
  --tag atomic-reactor
```

Details: [write the Containerfile](#write-the-dockerfile-or-containerfile), [build the container](#build-the-container)
