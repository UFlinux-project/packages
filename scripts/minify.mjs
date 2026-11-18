import { readFile, readdir, writeFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { transform } from "esbuild";
import { minify } from "html-minifier-terser";

const root = "dist";
const loaders = new Map([[".css", "css"], [".js", "js"], [".mjs", "js"]]);
let count = 0;
let savedBytes = 0;

for (const entry of await readdir(root, { recursive: true, withFileTypes: true })) {
  if (!entry.isFile()) continue;
  const extension = extname(entry.name);
  const loader = loaders.get(extension);
  if (extension !== ".html" && !loader) continue;

  const path = join(entry.parentPath, entry.name);
  const source = await readFile(path, "utf8");
  let output;
  try {
    output = extension === ".html"
      ? await minify(source, {
          collapseWhitespace: true,
          conservativeCollapse: true,
          minifyCSS: true,
          minifyJS: { module: true },
        })
      : (await transform(source, {
          loader, sourcefile: path, minify: true, legalComments: "inline",
        })).code;
  } catch (error) {
    throw new Error(`Could not minify ${path}`, { cause: error });
  }
  await writeFile(path, output);
  count++;
  savedBytes += Buffer.byteLength(source) - Buffer.byteLength(output);
}

console.log(`Minified ${count} HTML, CSS, and JavaScript files (${savedBytes} bytes saved)`);
