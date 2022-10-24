# Usage

## Example

Let's show Cachi2 usage by building the glorious [fzf](https://github.com/junegunn/fzf) CLI tool hermetically. To follow
along, clone the repository to your local disk.

```shell
git clone https://github.com/junegunn/fzf --branch=0.34.0
```

If you don't have Cachi2 installed locally, you can run it via the [container image](../README.md#container-image).

### Pre-fetch dependencies

```shell
cachi2 fetch-deps \
  --source ./fzf \
  --output ./cachi2-output \
  --package '{"path": ".", "type": "gomod"}'
```

* `--source` - the path to a *git repository* on the local disk
* `--output` - the path to the directory where Cachi2 will write all output
* `--package` - specifies a *package* (a directory) within the repository to process

Note that Cachi2 does not auto-detect which package managers your project uses. You need to tell Cachi2 what to process
using the `--package` parameter. In the example above, the package is a go module located at the root of the fzf repo,
hence the relative path is `.`.

The `--package` parameter can be used more than once and accepts alternative forms of input:

* simple: `--package=gomod`, same as `{"path": ".", "type": "gomod"}`
* JSON object: `{"path": "subpath/to/other/module", "type": "gomod"}`
* JSON array: `[{"path": ".", "type": "gomod"}, {"path": "subpath/to/other/module", "type": "gomod"}]`

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
do with the target path where we will mount the output directory during the build.

See also `cachi2 generate-env --help`.

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
sudo podman network create --internal isolated-network
sudo podman build . \
  --volume "$(realpath ./cachi2-output)":/tmp/cachi2-output:Z \
  --volume "$(realpath ./cachi2.env)":/tmp/cachi2.env:Z \
  --network isolated-network \
  --tag fzf

# test that it worked
sudo podman run --rm -ti fzf
```

We use the `--volume` option to mount Cachi2 resources into the container build - the output directory at
/tmp/cachi2-output/ and the environment file at /tmp/cachi2.env.

The path where the output directory gets mounted is important. Some environment variables are absolute paths to content
in the output directory; if the directory is not at the expected path, the paths will be wrong. Remember the
`--for-output-dir` used when [generating the env file](#generate-environment-variables)? The absolute path to
./cachi2-output on your machine is (probably) not /tmp/cachi2-output. That is why we had to tell the generate-env
command what the path inside the container is eventually going to be.

As for the network-isolation part, we solve it by using an internal podman network. An easier way to achieve this is
`podman build --network=none` or `buildah bud --network=none` (no sudo needed), but your podman/buildah version needs to
contain the fix for [buildah#4227](https://github.com/containers/buildah/issues/4227).
