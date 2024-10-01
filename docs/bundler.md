# Bundler

<https://bundler.io/>

## Prerequisites

To use Cachi2 with Bundler locally, ensure you have Ruby and Bundler installed
on your system.

```bash
sudo dnf install rubygem-bundler
```

Then ensure you have both, **Gemfile** and **Gemfile.lock** in your project
directory. We parse the **Gemfile.lock** to pre-fetch all dependencies
specified in that file.

## Basic usage

Run the following command in your terminal to pre-fetch your project's
dependencies. The command will download all dependencies specified in the
**Gemfile.lock** to the specified output directory.

```bash
cd path-to-your-ruby-project
cachi2 fetch-deps bundler
```

In addition, it will prepare the necessary environment variables and
configuration files for the build phase. See the following sections for more
information.

### Gems

Each gem has a name, version, and platform. If the platform is "ruby", it means
that it should work on any platform Ruby runs on. Using the ruby platform means
ignoring the current machine's platform and installing only ruby platform gems.
As a result, gems with native extensions will be compiled from the source.

However, occasionally some gems do not have a version for the ruby platform and
are only available as pre-compiled binaries. In this case, you may need to enable
the pre-fetching of gems for specific platforms to avoid potential failures with
the `allow_binary` option set to `true` when running the `fetch-deps` command.

```bash
cd path-to-your-ruby-project
cachi2 fetch-deps '{"type": "bundler", "allow_binary": "true"}'
```

By default, the `allow_binary` option is disabled.

## Configuration

[Bundler](https://bundler.io/v2.5/man/bundle-config.1.html#DESCRIPTION) uses
an unorthodox system when dealing with configuration options. The highest
precedence is given to the config file, and then to the environment variables.
This is a current limitation of Bundler, that we had to work around. We may
drop the workaround if this ends up being addressed in future Bundler releases.

The order of precedence for Bundler configuration options is as follows:

1. Local config (`<project_root>/.bundle/config or $BUNDLE_APP_CONFIG/config`)
2. Environment variables (ENV)
3. Global config (`~/.bundle/config`)
4. Bundler default config

We set the following configuration options to ensure that the build process
works correctly:

- BUNDLE_CACHE_PATH: "${output_dir}/deps/bundler"
- BUNDLE_DEPLOYMENT: "true"
- BUNDLE_NO_PRUNE: "true"
- BUNDLE_VERSION: "system"

### BUNDLE_CACHE_PATH

The directory that Bundler will look into when installing gems.

### BUNDLE_DEPLOYMENT

Disallow changes to the **Gemfile**. When the **Gemfile** is changed
and the lockfile has not been updated, running Bundler commands will be blocked.

### BUNDLE_NO_PRUNE

Leave outdated gems unpruned.

### BUNDLE_VERSION

The version of Bundler to use when running under the Bundler environment.

**Note**: _A prefetch could fail when Bundler versions differ between the build
system and lockfile and when the former is outdated. Therefore we do not recommend
using mismatching or outdated versions of Bundler in build systems as this might
result in unexpected failures._

To create the configuration file, run the following command.

```bash
cachi2 inject-files --for-output-dir /tmp/cachi2-output cachi2-output
```

You should see a log message that the file was created successfully.
Lastly, you need to set the `BUNDLE_APP_CONFIG` environment variable to point
to the copied configuration file.

```bash
cachi2 generate-env --output ./cachi2.env --for-output-dir /tmp/cachi2-output ./cachi2-output
```

```bash
# cat cachi2.env
export BUNDLE_APP_CONFIG=/tmp/cachi2-output/bundler/config_override
```

The generated environment file should be sourced before running any Bundler command.

### Limitations

Since the local configuration takes higher precedence than the environment
variables (except `BUNDLE_APP_CONFIG`), we copy the configuration file and
overwrite the environment variables above. Then, we change the
`BUNDLE_APP_CONFIG` environment variable to point to the new configuration file.

It should not affect the build process unless you have multiple packages in
your repository with different configuration settings. In that case, you may
have to adjust the build phase accordingly.

## Hermetic build

After using the `fetch-deps`, `inject-files`, and `generate-env` commands
to set up the directory, building the Dockerfile will produce a container with
the application fully compiled without any network access. The build will be
hermetic and reproducible.

```Dockerfile
FROM docker.io/library/ruby:latest

WORKDIR /app

COPY Gemfile .
COPY Gemfile.lock .

...

RUN . /tmp/cachi2.env && bundle install

...
```

Assuming `cachi2-output` and `cachi2.env` are in the same directory as the
Dockerfile, build the image with the following command:

```bash
podman build . \
  --volume "$(realpath ./cachi2-output)":/tmp/cachi2-output:Z \
  --volume "$(realpath ./cachi2.env)":/tmp/cachi2.env:Z \
  --network none \
  --tag my-ruby-app
```

## Unsupported features

- checksum validation (blocked by pending official support)
- downloading the Bundler version specified in the **Gemfile.lock**
- reporting development dependencies
- plugins
