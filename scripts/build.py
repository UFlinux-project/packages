"""Build the two localized views and their shared package data."""
import html
import os
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from urllib.parse import unquote

from catalog import DIGEST_PATH, digest, load_catalog, package_group, serialize

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist"
SITE = os.getenv("SITE_ORIGIN", "https://pkgs.uflinux.org").rstrip("/")
PAGE_SIZE = 25
WASM_STARTUP = """<script>
  if (location.search) document.documentElement.classList.add("pending-query");
</script>
<script type="module">
  try {
    const { default: init } = await import("/assets/wasm/packages.js");
    await init();
  } catch (error) {
    console.error(error);
    const status = document.querySelector("#status");
    status.textContent = status.dataset.loadError;
    document.querySelector("#retry").hidden = false;
  } finally {
    document.documentElement.classList.remove("pending-query");
  }
</script>"""


def esc(value):
    return html.escape(str(value))


def localized(lang, route):
    return ("/cs" if lang == "cs" else "") + route


def layout(lang, route, title, content, *, script=False, missing=False):
    def tr(en, cs):
        return cs if lang == "cs" else en

    local_home = localized(lang, "/")
    home = f"https://uflinux.org{local_home}"
    other = tr("cs", "en")
    links = [
        (home, tr("Overview", "Přehled"), False),
        (home + "downloads/", tr("Downloads", "Ke stažení"), False),
        (home + "guide/", tr("Get started", "Začínáme"), False),
        (f"https://docs.uflinux.org{local_home}", tr("Documentation", "Dokumentace"), False),
        (local_home, tr("Packages", "Balíčky"), not missing),
    ]
    nav = "".join(
        f'<a href="{esc(url)}"{" aria-current=page" if current else ""}>{label}</a>'
        for url, label, current in links
    )
    alternate = "".join(
        f'<link rel="alternate" hreflang="{locale}" href="{esc(SITE + localized(locale, route))}">'
        for locale in ("en", "cs")
    )
    meta = '<meta name="robots" content="noindex">' if missing else (
        f'<link rel="canonical" href="{esc(SITE + localized(lang, route))}">{alternate}'
    )
    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#181818"><meta name="color-scheme" content="dark">
  <title>{esc(title)} · UFlinux</title>
  {meta}
  <link rel="icon" href="/assets/logo.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/assets/site.css">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Ubuntu:wght@400;500;700&amp;display=optional">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/7.3.1/css/fontawesome.min.css" integrity="sha384-m8DKa0MtZAZlyNgF18TSkQRYTPDY0sEELpwK2YijfYnVFH8kxiaO6hvopM168nue" crossorigin="anonymous">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/7.3.1/css/solid.min.css" integrity="sha384-p/nJzgOJxEnSeUkMQ0nk5oPsUT5x8eOWi6pxU2ls9qcO9B78dCvZk0JSAOXWXUQN" crossorigin="anonymous">
  {WASM_STARTUP if script else ""}
</head>
<body>
  <a class="skip" href="#main">{tr("Skip to content", "Přejít k obsahu")}</a>
  <header class="header">
    <a class="brand" href="{home}"><img src="/assets/logo.svg" width="35" height="35" alt=""><span class="wordmark" translate="no">UFlinux.</span></a>
    <nav aria-label="{tr("Main navigation", "Hlavní navigace")}">{nav}</nav>
    <div class="language-switcher">
      <details>
        <summary aria-label="{tr('Select language', 'Vybrat jazyk')}"><i class="fa-solid fa-language" aria-hidden="true"></i>{tr('English', 'Čeština')}<i class="fa-solid fa-chevron-down" aria-hidden="true"></i></summary>
        <div><a href="{esc(localized(lang, route if not missing else '/'))}" lang="{lang}" aria-current="true">{tr('English', 'Čeština')}</a>
        <a href="{esc(localized(other, route if not missing else '/'))}" lang="{other}" data-alternate>{tr('Čeština', 'English')}</a></div>
      </details>
    </div>
  </header>
  <main id="main" tabindex="-1">{content}</main>
  <footer>
    <div><a class="brand" href="{home}" translate="no">UFlinux.</a><p>{tr("A small system. Room for your ideas.", "Malý systém. Prostor pro vaše nápady.")}</p></div>
    <nav aria-label="{tr("Footer links", "Odkazy v zápatí")}">
      <a href="https://github.com/UFlinux-project/uflinux3">GitHub ↗</a>
      <a href="https://github.com/UFlinux-project/packages/issues">{tr("Report an issue", "Nahlásit chybu")} ↗</a>
      <a href="{home}credits/">{tr("Artwork &amp; licenses", "Autoři a licence")}</a>
    </nav>
    <small>{tr("© UFlinux contributors · Built in the open.", "© Přispěvatelé UFlinux · Vyvíjeno otevřeně.")}</small>
  </footer>
</body>
</html>
"""


def catalog_page(lang, records):
    def tr(en, cs):
        return cs if lang == "cs" else en

    title = tr("Packages", "Balíčky")
    filters = [
        ("repository", tr("Repository", "Repozitář")),
        ("branch", tr("Branch", "Větev")),
        ("architecture", tr("Architecture", "Architektura")),
        ("maintainer", tr("Maintainer", "Správce")),
    ]
    selects = []
    for key, label in filters:
        values = sorted({pkg[key] for pkg in records if pkg[key]})
        options = "".join(f'<option value="{esc(value)}">{esc(value)}</option>' for value in values)
        selects.append(f'<label>{label}<select name="{key}"><option value="">{tr("All", "Vše")}</option>{options}</select></label>')
    headings = [
        tr("Package", "Balíček"), tr("Version", "Verze"), tr("Repository", "Repozitář"),
        tr("Branch", "Větev"), tr("Architecture", "Architektura"), tr("License", "Licence"),
        tr("Built", "Sestaveno"),
    ]
    latest = [pkg for pkg in records if pkg["latest"]]
    pages = ceil(len(latest) / PAGE_SIZE)
    total = format(len(latest), ",").replace(",", "\u00a0" if lang == "cs" else ",")
    shown = min(len(latest), PAGE_SIZE)
    status = tr(f"1–{shown} of {total} results", f"1–{shown} z {total} výsledků")
    page_label = tr(f"Page 1 of {pages}", f"Strana 1 z {pages}")
    rows = []
    for pkg in latest[:PAGE_SIZE]:
        built = datetime.fromtimestamp(pkg["buildTime"], timezone.utc).date().isoformat() if pkg["buildTime"] else ""
        cells = (pkg["version"], pkg["repository"], pkg["branch"], pkg["architecture"], pkg["license"], built)
        columns = "".join(f"<td>{esc(value or '—')}</td>" for value in cells)
        href = esc(localized(lang, pkg["url"]))
        name = esc(pkg["name"])
        rows.append(f'<tr><th scope="row"><a href="{href}">{name}</a></th>{columns}</tr>')

    content = f"""
    <h1>{title}</h1>
    <p class="lead">{tr("Browse packages published by UFLinux for the base system and apps.", "Procházejte balíčky základního systému a aplikací vydávané projektem UFLinux.")}</p>
    <noscript><p>{tr("Enable JavaScript to search the package catalog.", "Pro vyhledávání v katalogu balíčků povolte JavaScript.")}</p></noscript>
    <form id="filters" role="search" autocomplete="off" inert>
      <label class="query">{tr("Package name or description", "Název nebo popis balíčku")}<input type="search" name="q" placeholder="{tr('e.g. uflinux-files', 'např. uflinux-files')}" maxlength="200"></label>
      {"".join(selects)}
      <div class="filter-actions">
        <label class="older"><input type="checkbox" name="versions" value="all">{tr("Include older versions", "Zahrnout starší verze")}</label>
        <div class="buttons"><button class="primary" type="submit">{tr("Search", "Hledat")}</button><button type="reset">{tr("Reset", "Vymazat")}</button></div>
      </div>
    </form>
    <section id="results" aria-label="{tr('Package results', 'Výsledky hledání')}">
      <p id="status" role="status" data-load-error="{tr('Package search could not load.', 'Vyhledávání balíčků se nepodařilo načíst.')}">{status}</p>
      <a id="retry" class="button" href="" hidden>{tr("Try again", "Zkusit znovu")}</a>
      <div class="table-wrap" id="table-wrap" tabindex="0" role="region" aria-label="{tr('Package results table', 'Tabulka výsledků')}">
        <table><thead><tr>{"".join(f'<th scope="col">{heading}</th>' for heading in headings)}</tr></thead><tbody id="rows">{"".join(rows)}</tbody></table>
      </div>
      <nav id="pagination" aria-label="{tr('Results pages', 'Stránky výsledků')}" inert{" hidden" if pages <= 1 else ""}>
        <a class="button" id="previous" hidden>{tr("Previous", "Předchozí")}</a>
        <span id="page-count">{page_label}</span>
        <a class="button" id="next" href="?page=2">{tr("Next", "Další")}</a>
      </nav>
    </section>"""
    return layout(lang, "/", title, content, script=True)


def size_label(size):
    if size >= 1024**2:
        return f"{size / 1024**2:.1f} MiB"
    if size >= 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size} B"


def package_page(lang, pkg, versions):
    def tr(en, cs):
        return cs if lang == "cs" else en

    def dependency_list(en, cs, key):
        if not pkg[key]:
            return ""
        items = "".join(f"<li><code>{esc(entry)}</code></li>" for entry in pkg[key])
        return f"<section><h2>{tr(en, cs)}</h2><ul class='dependencies'>{items}</ul></section>"

    built = datetime.fromtimestamp(pkg["buildTime"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if pkg["buildTime"] else ""
    project = pkg["projectUrl"]
    facts = [
        (tr("Version", "Verze"), esc(pkg["version"])),
        (tr("Repository", "Repozitář"), esc(pkg["repository"])),
        (tr("Branch", "Větev"), esc(pkg["branch"])),
        (tr("Architecture", "Architektura"), esc(pkg["architecture"])),
        (tr("Package architecture", "Architektura balíčku"), esc(pkg["packageArchitecture"]) if pkg["packageArchitecture"] != pkg["architecture"] else ""),
        (tr("License", "Licence"), esc(pkg["license"])),
        (tr("Origin", "Zdrojový balíček"), esc(pkg["origin"])),
        (tr("Maintainer", "Správce"), esc(pkg["maintainer"])),
        (tr("Build date", "Datum sestavení"), built),
        (tr("Download size", "Velikost ke stažení"), size_label(pkg["downloadSize"])),
        (tr("Installed size", "Velikost po instalaci"), size_label(pkg["installedSize"])),
        (tr("Project", "Projekt"), f'<a href="{esc(project)}">{esc(project)}</a>' if project else ""),
    ]
    details = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in facts if value)
    history = []
    for entry in versions:
        version = esc(entry["version"])
        if entry == pkg:
            history.append(f'<li><span aria-current="page">{version}</span></li>')
        else:
            history.append(f'<li><a href="{esc(localized(lang, entry["url"]))}">{version}</a></li>')
    version_list = f'<section><h2>{tr("Indexed versions", "Verze v katalogu")}</h2><ul class="versions">{"".join(history)}</ul></section>' if len(history) > 1 else ""
    content = f"""
    <a class="back" href="{localized(lang, '/')}">← {tr("Browse packages", "Procházet balíčky")}</a>
    <h1>{esc(pkg["name"])}</h1>
    <p class="lead">{esc(pkg["description"])}</p>
    <a class="button primary download" href="{esc(pkg["downloadUrl"])}">{tr("Download APK", "Stáhnout APK")}</a>
    <dl>{details}</dl>
    {version_list}
    {dependency_list("Dependencies", "Závislosti", "depends")}
    {dependency_list("Provides", "Poskytuje", "provides")}
    {dependency_list("Install if", "Instalovat, pokud", "installIf")}
    """
    return layout(lang, pkg["url"], f'{pkg["name"]} {pkg["version"]}', content)


def write(route, document):
    directory = OUT / unquote(route).lstrip("/")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(document, encoding="utf-8")


def build():
    catalog = load_catalog()
    records = catalog["packages"]
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "assets", OUT / "assets")
    (OUT / "data").mkdir()
    (OUT / "data/catalog.json").write_bytes(serialize(catalog))
    (OUT / DIGEST_PATH.lstrip("/")).write_text(digest(catalog) + "\n", encoding="ascii")
    groups = defaultdict(list)
    for record in records:
        groups[package_group(record)].append(record)
    for lang in ("en", "cs"):
        write(localized(lang, "/"), catalog_page(lang, records))
        for record in records:
            write(localized(lang, record["url"]), package_page(lang, record, groups[package_group(record)]))
    missing = '<h1>Page not found</h1><p><a class="back" href="/">Browse packages</a></p>'
    (OUT / "404.html").write_text(layout("en", "/", "Page not found", missing, missing=True), encoding="utf-8")
    shutil.copyfile(ROOT / "_headers", OUT / "_headers")
    print(f"Built {len(records)} package versions in English and Czech")


if __name__ == "__main__":
    build()
