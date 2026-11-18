import { mkdir, readFile, writeFile } from "node:fs/promises";
import { gzipSync, gunzipSync } from "node:zlib";
import * as pagefind from "pagefind";

const { packages } = JSON.parse(await readFile("dist/data/catalog.json", "utf8"));
try {
  const { index, errors } = await pagefind.createIndex({ includeCharacters: "-+._" });
  if (errors.length) throw new Error(errors.join("\n"));

  for (const [rank, pkg] of packages.entries()) {
    const aliases = pkg.name.split(/[-+._]+/).join(" ");
    const { errors } = await index.addCustomRecord({
      url: pkg.url,
      language: "en",
      content: [pkg.name, aliases, pkg.description].join(" "),
      filters: {
        packageName: [pkg.name.toLowerCase()],
        repository: [pkg.repository],
        branch: [pkg.branch],
        architecture: [pkg.architecture],
        maintainer: [pkg.maintainer],
        latest: [pkg.latest ? "yes" : "no"],
      },
      sort: { browse: String(rank) },
    });
    if (errors.length) throw new Error(pkg.url + ": " + errors.join("\n"));
  }

  const { files, errors: fileErrors } = await index.getFiles();
  if (fileErrors.length) throw new Error(fileErrors.join("\n"));

  // Package the pinned Pagefind format and the matching display rows for Rust.
  const metadata = [];
  const indexes = [];
  const filters = [];
  const rows = {};
  const packagesByUrl = new Map(packages.map(pkg => [pkg.url, pkg]));
  for (const { path, content } of files) {
    const extension = path.split(".").at(-1);
    if (!["pf_meta", "pf_index", "pf_filter", "pf_fragment"].includes(extension)) continue;
    const payload = gunzipSync(content);
    const magic = "pagefind_dcd";
    if (payload.subarray(0, magic.length).toString() !== magic) {
      throw new Error(`Unexpected Pagefind header in ${path}`);
    }
    const data = payload.subarray(magic.length);
    if (extension === "pf_meta") metadata.push(data.toString("base64"));
    if (extension === "pf_index") indexes.push(data.toString("base64"));
    if (extension === "pf_filter") filters.push(data.toString("base64"));
    if (extension === "pf_fragment") {
      const { url } = JSON.parse(data.toString("utf8"));
      const pkg = packagesByUrl.get(url);
      if (!pkg) throw new Error(`Pagefind fragment references unknown package ${url}`);
      const { name, version, repository, branch, architecture, license, buildTime } = pkg;
      const hash = path.split("/").at(-1).slice(0, -".pf_fragment".length);
      rows[hash] = { url, name, version, repository, branch, architecture, license, buildTime };
      packagesByUrl.delete(url);
    }
  }
  if (metadata.length !== 1 || packagesByUrl.size !== 0 || !indexes.length || !filters.length) {
    throw new Error("Pagefind bundle is incomplete");
  }
  await mkdir("target", { recursive: true });
  await writeFile("target/catalog-index.json.gz", gzipSync(JSON.stringify({
    metadata: metadata[0], indexes, filters, rows,
  })));
  console.log(`Indexed ${packages.length} package versions with Pagefind`);
} finally {
  await pagefind.close();
}
