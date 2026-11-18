# UFLinux Packages

The English and Czech package browser for [pkgs.uflinux.org](https://pkgs.uflinux.org/).
It indexes the packages published in UFLinux's two APK repositories for Alpine v3.24.

## Build and check locally

Use Node.js 22.23.4 (see `.node-version`), Python 3.13 or newer, and Rust via `rustup`.
`rust-toolchain.toml` selects the stable Rust channel and the WebAssembly target.
`npm run build` checks for the latest stable release and installs rustup under
`target/rust-bootstrap/` on build images without it. This requires network access
to the Rust distribution servers and uses `curl` to install rustup when needed.

```sh
npm ci
npm test
npm run build
python3 -m http.server --directory dist 8000
```

The build needs HTTPS access to all ten configured APK indexes. The repository matrix
lives in `scripts/catalog.py`. The normalized, deterministically ordered
`dist/data/catalog.json` feeds the static package pages and the Pagefind custom records.
The build embeds the Pagefind index and display rows in
`dist/assets/wasm/packages_bg.wasm`. The single module contains the Pagefind Rust search
engine and the browser UI in `src/`. The catalog HTML starts the module through the
generated wasm-bindgen JavaScript. Package details remain static HTML, and APK
downloads link directly to the source repositories.

After building the WASM bundle, `npm run build` minifies the HTML, CSS, and JavaScript
in `dist/`, including the generated browser loader.

The Pagefind npm package and Rust source are pinned to the same release because the
embedded index uses that release’s internal format. Upgrade and test both together.

## Cloudflare Pages

Connect `UFlinux-project/packages` using Git integration and use these build settings.

| Setting | Value |
| --- | --- |
| Production branch | `main` |
| Framework preset | None |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Environment variables | `PYTHON_VERSION=3.13` |

After the first deployment, add `pkgs.uflinux.org` under the Pages project's custom
domains and verify it serves the catalog. Then roll out the Packages navbar links on
the website and docs.

Create a deploy hook for `main` and save its URL as the repository Actions secret
`CLOUDFLARE_PAGES_DEPLOY_HOOK`. Run **Refresh package catalog** manually to verify the
configuration. Its hourly schedule compares both live repositories against the
deployed `/data/catalog.sha256` and requests a rebuild when the contents change.
Check the Actions and Pages build logs for failures. Pages continues serving the
last successful deploy when a build fails.

`SITE_ORIGIN` defaults to `https://pkgs.uflinux.org`. For another production domain
set it in both the Pages build environment and the refresh workflow.
