# yarn

<https://v3.yarnpkg.com/>

* Overview [in the README][readme-yarn]
* [Cachi2's Yarn support scope](#cachi2s-yarn-support-scope)
    * [Supported Yarn versions](#supported-yarn-versions)
    * [Supported Yarn protocols/locators](#supported-yarn-protocolslocators)
    * [Dealing with .yarnrc.yml](#dealing-with-yarnrcyml)
    * [Dealing with Yarn Zero-Installs](#dealing-with-yarn-zero-installs)
    * [Dealing with plugins](#dealing-with-plugins)
* [Specifying packages to process](#specifying-packages-to-process)
    * [Controlling Yarn's behavior](#controlling-yarns-behavior)
    * [Downloading dependencies](#downloading-dependencies)
    * [Known pitfalls](#known-pitfalls)
* [Using fetched dependencies](#using-fetched-dependencies)
    * [Building your project using the pre-fetched Yarn dependency
cache](#building-your-project-using-the-pre-fetched-yarn-dependency-cache)

## Cachi2's Yarn support scope

### Supported Yarn versions
Cachi2 only currently only supports Yarn in version 3.

_Note: newer versions of Yarn are likely to be added in future releases._

### Supported Yarn protocols/locators

Cachi2 currently supports all standard
[Yarn v3 protocols](<https://v3.yarnpkg.com/features/protocols/>) except for:
- [Exec](https://v3.yarnpkg.com/features/protocols#exec)
- [Git/GitHub](https://v3.yarnpkg.com/features/protocols#git)

Due to the nature of how the two protocols above work, mainly related to potentially executing
arbitrary code, adding support for them with future releases of Cachi2 is unlikely. For further
details on Yarn protocols and their practical ``package.json`` examples, please head to the
official Yarn documentation on protocols linked earlier in this section.

### Dealing with .yarnrc.yml
Cachi2 parses the project's ``.yarnrc.yml`` file and analyzes configuration settings. Before cachi2
proceeds with the actual dependency fetching, it verifies whether all [configuration
settings](https://v3.yarnpkg.com/configuration/yarnrc) that set a path to a resource don't point
outside of the source repository, so in order to avoid any issues reported by Cachi2 in this regard
make sure all your project resource references are bound by the repository. Part of the analysis of
the repository's ``.yarnrc.yml`` file is detection of plugin usage which is further explained in
[Dealing with plugins](#dealing-with-plugins).

### Dealing with Yarn Zero-Installs

Yarn's [PnP Zero-Installs](https://v3.yarnpkg.com/features/zero-installs/) are unsupported due to
the potentially [unplugged dependencies](https://v3.yarnpkg.com/advanced/lexicon#unplugged-package)
checked into the repository which simply make it impossible for the Yarn cache to be checked for
integrity using Yarn's standard tooling (i.e. ``yarn install --check-cache``).

_Note: the same applies to dealing with the ``node_modules`` top level directory which, if checked
into the repository, can also serve the Zero-Install purpose. If you need further information on
which dependency linking mode is used, have a look at the
[nodeLinker](https://v3.yarnpkg.com/configuration/yarnrc/#nodeLinker) and on the
[PnP](https://v3.yarnpkg.com/features/pnp/) approach in general._

_Also note that we may reconsider our initial decision when it comes to Zero-Installs provided the
input repository doesn't rely on any dependencies which may include install scripts leading to
their unpacking in a form of ``.yarn/unplugged`` entries._

### Dealing with plugins
Due to the nature of plugins (which can potentially execute arbitrary code, by e.g. adding new
protocol resolvers), **all** plugins except for the vendored
[exec](https://v3.yarnpkg.com/features/plugins#official-plugins) one are disabled during the
dependency pre-fetch stage to ensure no other changes apart from downloading dependencies took
action.

_Note: cachi2 doesn't taint your project files, so any plugins you set will be enabled normally
in your build environment, the only problem that can arise is if any of your specified plugins adds
a new protocol which cachi2 doesn't know about in which case the dependency pre-fetch stage will
fail with an error._

## Specifying packages to process

A package is a file or directory that is described by a
[package.json](https://v3.yarnpkg.com/configuration/manifest/) file (also called a
manifest).

Cachi2 ``fetch-deps`` shell command:

```shell
cachi2 fetch-deps \
  --source ./my-repo \
  --output ./cachi2-output \
  '<JSON input>'
```

JSON input:
```jsonc
{
  // "yarn" tells Cachi2 to process Yarn packages
  "type": "yarn",
  // path to the package (relative to the --source directory)
  // defaults to "."
  "path": ".",
}
```

or more simply by just invoking:
``cachi2 fetch-deps yarn``

For complete example of how to pre-fetch dependencies, see [Pre-fetch dependencies][usage-prefetch].

### Controlling Yarn's behavior

Cachi2 instructs Yarn to download dependencies explicitly declared in ``package.json``. The
dependencies are then further managed in a ``yarn.lock`` file that Yarn CLI manages automatically
and creates it if missing. However, **Cachi2 will refuse to process your repository if the file is
missing**, so be sure to check that file into the repository. Also make sure that the file is up
to date for which you can use [yarn
install](https://v3.yarnpkg.com/getting-started/usage/#installing-all-the-dependencies).

### Downloading dependencies
If Yarn is configured to operate in the [PnP mode](https://v3.yarnpkg.com/features/pnp) (the
default in Yarn v3) Yarn will store all dependencies as [ZIP
archives](https://v3.yarnpkg.com/features/pnp/#packages-are-stored-inside-zip-archives-how-can-i-access-their-files).

Once the source repository analysis and verification described in the earlier sections of this
document has been completed, then it's essentially just a matter of cachi2 internally invoking
``yarn install --mode=skip-build`` to fetch all dependencies (including transitive dependencies).

### Known pitfalls
If your repository isn't in a pristine state (i.e. you tried to run ``yarn install`` previously on
your own without Cachi2) what may happen is that Cachi2 will assume the repository makes use of
[Zero-Installs](#dealing-with-yarn-zero-installs). The workaround here is simple, just run ``yarn
cache clean`` and cachi2 will then process your repository as normal.
    
## Using fetched dependencies

See also [usage.md](usage.md) for a complete example of Cachi2 usage.

Cachi2 downloads the Yarn dependencies into the ``deps/yarn/`` subpath of the output directory (see
the snippet below).

```text
cachi2-output/deps/yarn
└── cache
    ├── abbrev-npm-1.1.1-3659247eab-8.zip
    ├── agent-base-npm-6.0.2-428f325a93-8.zip
    ├── agentkeepalive-npm-4.3.0-ac3d8e6807-8.zip
    ├── aggregate-error-npm-3.1.0-415a406f4e-8.zip
    ├── ansi-regex-npm-3.0.1-01f44078a3-8.zip
...
```

### Building your project using the pre-fetched Yarn dependency cache
In order to use the cachi2 pre-fetched Yarn dependency cache obtained from the previous step
several environment variables need to be set in your build environment.
See [Generate environment variables][usage-genenv] for more details on how these can be
generated by cachi2 automatically in a form of a environment file that can sourced as part of your
container build recipe. Here's a snippet of the most important variables cachi2 needs to be set in
the build environment along with explanation:

```
# Point Yarn to our pre-populated global cache
YARN_GLOBAL_FOLDER=<cachi2_output_dir>/deps/yarn

# Yarn must not rely solely on the global cache (the pre-fetched one) because it'll likely only be
# available (i.e. mounted) during the (container) build time, but not runtime. We specifically want
# Yarn to copy those dependencies from the global cache to the project's local cache
YARN_ENABLE_GLOBAL_CACHE=false

# Must be set to true, otherwise Yarn will not make use of the pre-populated global cache we're
# pointing it at with YARN_GLOBAL_FOLDER at build time.
YARN_ENABLE_MIRROR=true

# Must be false otherwise 'yarn install' will fail to populate the project's local cache (pointed
# to by the 'cacheFolder' setting) from the global cache (the pre-fetched one).
YARN_ENABLE_IMMUTABLE_CACHE=false
```

[readme-yarn]: ../README.md#yarn
[usage-prefetch]: usage.md#pre-fetch-dependencies
[usage-genenv]: usage.md#generate-environment-variables
