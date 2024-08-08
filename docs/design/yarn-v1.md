# Cachi2 Yarn v1 (Yarn Classic) Prefetch Design

## Yarn Overview
[Yarn](https://github.com/yarnpkg/yarn) is a package manager for JavaScript. While Yarn v1.x is no longer actively developed and has been
succeeded by [Yarn v2+ (Berry)](https://github.com/yarnpkg/berry), it [remains widely used](https://npmtrends.com/yarn).

## Cachito Implementation Overview
Cachito supports the Yarn 1.x package manager. It directly parses package.json files and uses our [pyarn](https://github.com/containerbuildsystem/pyarn)
library to parse yarn.lock files. Dependencies are downloaded from their resolved URLs in the yarn.lock file without executing yarn itself.

Registry dependencies are fetched through a proxy repository in Nexus and the user's build is configured to use that proxy as the registry.

Non-registry dependencies are packed and uploaded to a hosted Nexus repository. The versions of these non-registry dependencies are
updated in package.json and yarn.lock to match those in the hosted repository.

## Proposed Cachi2 Implementation Overview

### Specifying a Yarn Package in a Cachi2 Request
Cachi2 users will specify ```yarn``` as the package manager or package type for all versions of Yarn. The presence of the ```__metadata``` field in yarn.lock
[can be used to differentiate](https://github.com/yarnpkg/berry/blob/13d5b3041794c33171808fdce635461ff4ab5c4e/packages/yarnpkg-core/sources/Project.ts#L374)
between Yarn v1.x and Yarn v2+ and route the request to the correct Yarn module in Cachi2.

### Offline Mirror
Prefetching dependencies for Yarn in Cachi2 will be done using Yarn's [offline mirror](https://classic.yarnpkg.com/blog/2016/11/24/offline-mirror/)
feature. When a project is configured to use the offline mirror, Yarn will store compressed archives in the mirror directory and can install
cached project dependencies from there later without network access.

The offline mirror also has a setting that controls [whether it removes package archives](https://classic.yarnpkg.com/en/docs/prune-offline-mirror/)
from the mirror directory when they are no longer needed. Cachi2 will want to disable automatic pruning of the offline mirror since we support multiple
yarn projects in a single request.

To enable the offline mirror, the following settings need to be applied either via .yarnrc or from environment variables:

    yarn-offline-mirror <absolute path to the request output directory>
    yarn-offline-mirror-pruning false

    YARN_YARN_OFFLINE_MIRROR=<absolute path to the request output directory>
    YARN_YARN_OFFLINE_MIRROR_PRUNING=false

### Installing Yarn (via Corepack)
Yarn commands will be executed in order to populate the offline mirror, so Yarn will need to be installed in the Cachi2 image. Corepack is
already being used to install Yarn in the Cachi2 Yarn v2+ implementation, so a similar approach is suggested.

Corepack installs the latest known-good Yarn v1.x release by default if no other version is specified explicitly. It seems reasonable to always
use the latest 1.x release for the prefetch, since 1.x is no longer under active development and we never previously allowed users to specify a specific
Yarn version to process their request in Cachito. We could add more flexibility with a later enhancement if needed.

Corepack could be configured to ignore user project configuration and use the global Yarn 1.x default by specifying the following
[environment variable](https://github.com/nodejs/corepack#environment-variables):

    COREPACK_ENABLE_PROJECT_SPEC=0

Alternatively we could configure corepack explicitly using the packageManager field in package.json like is done in Cachi2's Yarn v2+ implementation.

We will also need to set the following to prevent corepack from prompting for interactive user input when downloading Yarn:

    COREPACK_ENABLE_DOWNLOAD_PROMPT=0

### Project Configuration
The [package.json](https://classic.yarnpkg.com/en/docs/package-json) and [yarn.lock](https://classic.yarnpkg.com/en/docs/yarn-lock)
configuration files must be present in order to process the request.

The node_modules directory should be absent. I'm not certain at the moment how to guard against a user-specified modulesFolder at build-time.

Any additional configuration settings in the repository via [.yarnrc](https://classic.yarnpkg.com/en/docs/yarnrc) or .npmrc
files should be ignored (at least initially) for the prefetch by specifying ```--no-default-rc``` for the yarn install command.

We never previously honored user-defined settings with Cachito, but this can be investigated and implemented in Cachi2 in a follow-up. At minimum, the
limitation should be documented.

### SBOM Generation
The Yarn 1.x CLI doesn't provide enough information to generate an SBOM, so the yarn.lock and package.json files will need to
be parsed in order to gather the necessary data. The code used to process these files will need to be
[imported from or inspired by Cachito](https://github.com/containerbuildsystem/cachito/blob/63b8ec0ea615d114ccfa0d08dc0bec49e60e6a75/cachito/workers/pkg_managers/yarn.py)
and refactored/improved.

#### Key Points
 - The yarn.lock file can be parsed with [pyarn](https://github.com/containerbuildsystem/pyarn) like in cachito
 - Workspaces will need to be [processed separately](https://github.com/containerbuildsystem/cachito/blob/63b8ec0ea615d114ccfa0d08dc0bec49e60e6a75/cachito/workers/pkg_managers/yarn.py#L95) from package.json since they do not appear in the yarn.lock file
 - Dev dependencies can be [determined similiarly](https://github.com/containerbuildsystem/cachito/blob/63b8ec0ea615d114ccfa0d08dc0bec49e60e6a75/cachito/workers/pkg_managers/yarn.py#L140) to cachito
 - We will need to ensure that there are no collisions in the names of the archive files being added to the offline mirror

#### PURL Examples
[NPM PURL specification](https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst#npm)

##### Registry Package
```txt
pkg:npm/@optional-scope/package-name@1.0.0
```

##### URL Package
```txt
pkg:npm/package-name@1.0.0?checksum=sha512:checksum&download_url=https://example.com/package-name/0101010101010101010101010101010101010101.tar.gz
```

##### Git Package

```txt
pkg:npm/package-name@1.0.0?vcs_url=git%2Bhttps://example.com/namespace/package-name.git%0101010101010101010101010101010101010101
```

##### Workspace/File Package

```txt
pkg:npm/package-name@1.0.0?vcs_url=git%2Bhttps://example.com/namespace/package-name.git%0101010101010101010101010101010101010101#subpath
```

### Avoiding Arbitrary Code Execution
Yarn 1.x appears to honor the ```--ignore-scripts``` option for the install command. It can also be configured via environment variable.
Used https://github.com/chmeliik/js-lifecycle-scripts/tree/yarn to verify.

### Prefetch
The offline mirror in the request output directory will be populated by running the following Yarn command in the project root:

    yarn install --non-interactive --frozen-lockfile --disable-pnp --no-default-rc --ignore-engines

Command: [yarn install](https://classic.yarnpkg.com/en/docs/cli/install)

Options:
 - non-interactive: Disable interactive prompts
 - frozen-lockfile: Fail if yarn.lock updates are needed
 - disable-pnp: Disable Plug'n'Play installation
 - no-default-rc: Prevent Yarn from automatically detecting .yarnrc and .npmrc files
 - ignore-engines: Ignore the engine node version during the prefetch

 The behavior of Yarn can also be configured using select environment variables. The following ones should be set for the prefetch:

    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
    COREPACK_ENABLE_PROJECT_SPEC=0 (If we decide to use the global default)
    YARN_YARN_OFFLINE_MIRROR=<absolute path to the request output directory>
    YARN_YARN_OFFLINE_MIRROR_PRUNING=false
    YARN_IGNORE_PATH=true (Use the corepack yarn version, not any Yarn version specified by the user)
    YARN_IGNORE_SCRIPTS=true

### Build Configuration
The user build can be configured to use the offline mirror by configuring the following environment variables:

    YARN_YARN_OFFLINE_MIRROR=<request output directory>
    YARN_YARN_OFFLINE_MIRROR_PRUNING=false

## High-Level Procedure
 - Since we're executing Yarn commands directly, process the request in an [isolated temporary directory](https://github.com/containerbuildsystem/cachi2/blob/6953607b6ef52fd3f0bef7059d2c926767b1022b/cachi2/core/resolver.py#L41) to avoid any potential changes to the repository
 - Determine whether to process the request with yarn v1 or yarn v2+
 - Read the project files
   - Read/Require package.json
   - Read/Require yarn.lock
     - Ensure yarn.lock is formatted for Yarn 1.x
 - Verify the repository
   - Ensure node_modules directory is not present
 - Gather the SBOM Components
   - Get the main package component data from package.json
   - Get the workspaces from package.json and add a component for each workspace according to the workspace package.json data
   - Parse yarn.lock with pyarn and add components for each
     - Report missing integrity keys from yarn.lock as missing hashes
     - Ensure that there are no collisions between expected archive names in the offline mirror
 - Configure environment for the prefetch
   - Ensure offline mirror is used
   - Ensure offline mirror is not automatically pruned
   - Ensure package scripts are ignored
   - Ensure Yarn 1.x is used via corepack
 - Do the prefetch
   - Run yarn install
 - Configure environment for the user build
   - Ensure offline mirror is used from the request output
   - Ensure offline mirror is not pruned automatically

## Potential Follow-Ups
 - Allow versions of yarn other than the latest 1.x release to be specified by the user
 - Investigate allowing more user-specified settings during the prefetch via .yarnrc/.npmrc
