# gomod

<https://go.dev/ref/mod>

* Overview [in the README][readme-gomod]
* [Specifying modules to process](#specifying-modules-to-process)
* [Using fetched dependencies](#using-fetched-dependencies)
* [gomod flags](#gomod-flags)
* [Vendoring](#vendoring)
* [Understanding reported dependencies](#understanding-reported-dependencies)

## Specifying modules to process

```shell
cachi2 fetch-deps \
  --source ./my-repo \
  --output ./cachi2-output \
  '<modules JSON>'
```

Module[^misnomer] JSON:

```jsonc
{
  // "gomod" tells Cachi2 to process a go module
  "type": "gomod",
  // relative path to the module from the --source directory
  "path": "<path/to/module>"
}
```

The main argument accepts alternative forms of input, see [usage: pre-fetch-dependencies][usage-prefetch].

[^misnomer]: You may have noticed a slight naming issue. You use the main argument, also called PKG, to specify a *module* to
  process. Even worse, Go has packages as well (see [gomod vs go-package](#gomod-vs-go-package)). What gives?
  As far as we know, most languages/package managers use the opposite naming. For example, in [Python][py-modules],
  modules are `*.py` files, packages are collections of modules. In [npm][npm-modules], modules are directories/files
  you can `require()`, packages are the top-level directories with `package.json`. In Cachi2, we stick to the more
  common naming.

## Using fetched dependencies

See also [usage.md](usage.md) for a complete example of Cachi2 usage.

Cachi2 downloads the required modules into the deps/gomod/ subpath of the output directory (`cachi2-output/deps/gomod`).
Further down the file tree, at `cachi2-output/deps/gomod/pkg/mod`, is a directory formatted as the Go
[module cache](https://go.dev/ref/mod#module-cache).

```text
cachi2-output/deps/gomod/pkg/mod
└── cache
    └── download
        ├── github.com
        │   └── ...
        └── golang.org
            └── ...
```

To use this module cache during your build, set the GOMODCACHE environment variable. Cachi2 generates GOMODCACHE along
with other expected environment variables for you. See [usage: generate environment variables][usage-genenv] for more
details.

For more information on Go's environment variables:

```shell
go help environment
```

Note that the deps/gomod/ layout described above does not apply when using [vendoring](#vendoring). With vendoring
enabled, deps/gomod/ will be an empty directory. Instead, dependencies will be inside the vendor subdirectory of your
module.

```text
my-repo
└── vendor
    ├── github.com
    │   └── ...
    ├── golang.org
    │   └── ...
    └── modules.txt
```

Go will use the vendored dependencies automatically, but it's not a bad idea to set the environment variables generated
by Cachi2 anyway.

## gomod flags

The `cachi2 fetch-deps` command accepts the following gomod-related flags:

* [--cgo-disable](#--cgo-disable)
* [--force-gomod-tidy](#--force-gomod-tidy)
* --gomod-vendor - see [vendoring](#vendoring)
* --gomod-vendor-check - see [vendoring](#vendoring)

### --cgo-disable

Makes Cachi2 internally disable [cgo](https://pkg.go.dev/cmd/cgo) while processing your Go modules. Typically, you would
want to use this flag if your modules *do* use C code and Cachi2 is failing to process them. Cachi2 will not attempt to
disable cgo in your build (nor should you disable it yourself if you rely on C).

Disabling cgo should not prevent Cachi2 from fetching your Go dependencies as usual. Note that Cachi2 will not make any
attempts to fetch missing C libraries. If required, you would need to get them through other means.

### --force-gomod-tidy

Makes Cachi2 run `go mod tidy` after downloading dependencies.

⚠ This flag is questionable and may be removed in the future.

## Vendoring

Go supports [vendoring](https://go.dev/ref/mod#vendoring) to store the source code of all dependencies in the vendor/
directory alongside your module. Before go 1.17, `go mod vendor` used to download fewer dependencies than
`go mod download`. Starting with 1.17, that is no longer true - see the [overview][readme-gomod] in the README.

We generally discourage vendoring, but Cachi2 does support it nonetheless via the `--gomod-vendor` and
`--gomod-vendor-check` flags. Here's how Cachi2 behaves based on the flags used and the state of your repository:

* No flags - call go mod download to download dependencies. If there is a vendor/ directory, ignore it.
* `--gomod-vendor` - call go mod vendor to create the vendor/ directory. If there is one already, overwrite it.
* `--gomod-vendor-check` - if the vendor/ directory does not exist, do the same thing as gomod-vendor. Otherwise, call
  go mod vendor and verify that nothing changed in the vendor/ directory. If anything did change, raise an error.

⚠ The default (no flags) vendoring behavior is problematic, since Cachi2 does not know if you will use the vendored
dependencies or the downloaded ones. Cachi2 reports the downloaded ones, but cannot guarantee the report is correct.
The default behavior and the available flags may change in the future.

## Understanding reported dependencies

Cachi2 reports two (arguably three) different types of dependencies in the [metadata](metadata.md) generated for your
Go modules:

* **gomod** dependencies (Go modules)
* **go-package** dependencies (Go packages)
  * from the downloaded modules
  * from the [standard library](#stdlib-dependencies)

### gomod vs go-package

Best explained by the Go [modules documentation][go-modules-overview]:

> A module is a collection of packages that are released, versioned, and distributed together.

Your Go code imports individual *packages*, which come from *modules*. You might import a single package from a module
that provides many, but Go (and Cachi2) has to download the whole module anyway. Effectively, modules are the smallest
"unit of distribution." Go does have the ability to list the individual packages that your project imports. Cachi2 makes
use of this ability to report both the downloaded modules and the required packages.

The list of **go-package** dependencies reported by Cachi2 is the full set of packages (transitively) required by your
project.

The list of **gomod** dependencies is the set of modules that Cachi2 downloaded to satisfy the go-package dependencies.

Note that versioning applies to modules, not packages. When reporting the versions of Go packages, Cachi2 uses the
version of the module that provides the package.

#### How to match a package to a module?

Borrowing from the [modules documentation][go-modules-overview] again:

> For example, the module "golang.org/x/net" contains a package in the directory "html". That package’s path is
  "golang.org/x/net/html"

The name of a package starts with the name of the module that provides it.

#### In the source tree, what are modules? What are packages?

To simplify a little:

* Does the directory have a `go.mod` file? It's a module (provides packages).
* Does the directory have any `*.go` files? It's a package (is importable).
* Does it have both? It's both a module and a package.

### stdlib dependencies

Go is able to list even the standard library packages that your project imports. Cachi2 exposes these as **go-package**
dependencies, with caveats. Cachi2 uses some version of Go to list the dependencies. This may or may not be the same
version that you will use to build your project. We do not presume that the versions would be the same, hence why:

* the reported stdlib packages may be slightly inaccurate (e.g. new packages in new Go versions)
* the versions of stdlib packages are not reported

#### What identifies stdlib dependencies in the go-package list?

* does not have a version
* the name does not start with a hostname
  * `io/fs` - standard library
  * `golang.org/x/net` - external

[readme-gomod]: ../README.md#gomod
[usage-prefetch]: usage.md#pre-fetch-dependencies
[usage-genenv]: usage.md#generate-environment-variables
[go-modules-overview]: https://go.dev/ref/mod#modules-overview
[py-modules]: https://docs.python.org/3/tutorial/modules.html
[npm-modules]: https://docs.npmjs.com/about-packages-and-modules
