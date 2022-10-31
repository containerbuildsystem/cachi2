# Using Cachito requests locally

The typical mode of interaction with the output of a Cachito request is through
[OSBS][osbs-cachito]. Installing the content from a finished request without the help of
OSBS may seem like a daunting task, but is in fact not that difficult. Doing so may be
especially useful when trying to debug a build failure without going through the entire
process again.

## Get the relevant files

A Cachito request has three main parts: the **archive**, the **environment variables**
and the **configuration files**. Getting these manually is a bit of a pain, which is
why we use the [cachito-download.sh](../bin/cachito-download.sh) script to do it. You
will need `jq` and the typical unix utils to run this script.

```shell
cachito-download.sh https://cachito.example.org/api/v1/requests/1 /tmp/cachito-1
```

## Use the right environment

If you are debugging a build, make sure to match the target environment as closely as
possible. For example, if you are building a container based on `python:3.9`, then you
may want to try out the build in that base image.

```shell
cd /tmp/cachito-1/remote-source
# mount the remote-source/ directory, later you will run the build from there
podman run --rm -ti -v "$PWD:$PWD:z" python:3.9 bash
```

If using a container is not an option/not relevant, you should still consider using some
kind of virtual environment (such as the Python venv) and at least making sure that the
versions of your build tools match what you will be using in the real build.

## Run the build

In the container/virtual environment/your own system (not recommended), set the
environment variables provided by Cachito and run the build.

```shell
cd /tmp/cachito-1/remote-source
# source the env vars from the generated file
source cachito.env
# cd to the app/ directory, some package managers will only work properly from there
cd app
# run your package manager commands
pip install -r requirements.txt
npm install
go build
# etc.
```
