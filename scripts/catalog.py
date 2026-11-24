"""Read the APK v2 indexes and produce the catalog used by HTML and Pagefind."""
import hashlib
import io
import json
import re
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

BRANCH = "v3.24"
SOURCES = {
    "uflinux": ("https://repo.uflinux.org", ("x86_64", "aarch64", "ppc64le", "riscv64")),
    "uflinux-apps": ("https://apps-repo.uflinux.org", ("x86_64", "aarch64", "ppc64le", "riscv64")),
}
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]*")
DIGEST_PATH = "/data/catalog.sha256"
MAX_INDEX_BYTES = 8 * 1024 * 1024


def fetch(url, limit=MAX_INDEX_BYTES):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=15) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError(f"Response exceeds {limit} bytes: {url}")
            return data
        except (HTTPError, URLError, OSError) as error:
            if isinstance(error, HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def project_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return ""


def parse_index(data, repository, architecture):
    host = SOURCES[repository][0]
    base = f"{host}/apk/{BRANCH}/{repository}/{architecture}"
    # Signed APK v2 indexes concatenate a signature tar stream and a payload tar stream.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz", ignore_zeros=True) as archive:
        indexes = [member for member in archive if member.name == "APKINDEX"]
        if len(indexes) != 1 or not indexes[0].isfile() or indexes[0].size > MAX_INDEX_BYTES:
            raise ValueError("Expected one regular APKINDEX file")
        source = archive.extractfile(indexes[0]).read().decode("utf-8")
    records = []
    for paragraph in re.split(r"\n\s*\n", source.strip()):
        fields = {}
        for line in paragraph.splitlines():
            key, separator, value = line.partition(":")
            if not separator or not key or key in fields:
                raise ValueError(f"Invalid APKINDEX field: {line!r}")
            fields[key] = value
        name, version, declared_arch, checksum = (fields[key] for key in ("P", "V", "A", "C"))
        if not SEGMENT.fullmatch(name) or not SEGMENT.fullmatch(version) or not checksum:
            raise ValueError("Invalid package name, version, or checksum")
        if declared_arch not in (architecture, "noarch"):
            raise ValueError(f"Unexpected package architecture: {declared_arch}")
        filename = quote(f"{name}-{version}.apk", safe="")
        route = "/".join(quote(part, safe="") for part in (BRANCH, repository, architecture, name, version))
        numbers = {key: int(fields[key]) if fields.get(key) else 0 for key in ("t", "S", "I")}
        if any(value < 0 for value in numbers.values()) or numbers["t"] > 253402300799:
            raise ValueError("Invalid package timestamp or size")
        records.append({
            "branch": BRANCH,
            "repository": repository,
            "architecture": architecture,
            "packageArchitecture": declared_arch,
            "name": name,
            "version": version,
            "description": fields.get("T", ""),
            "projectUrl": project_url(fields.get("U", "")),
            "license": fields.get("L", ""),
            "origin": fields.get("o", ""),
            "maintainer": fields.get("m", "").split("<", 1)[0].strip(),
            "buildTime": numbers["t"],
            "downloadSize": numbers["S"],
            "installedSize": numbers["I"],
            "depends": fields.get("D", "").split(),
            "provides": fields.get("p", "").split(),
            "installIf": fields.get("i", "").split(),
            "indexChecksum": checksum,
            "url": f"/package/{route}/",
            "downloadUrl": f"{base}/{filename}",
        })
    return records


def package_group(record):
    return tuple(record[key] for key in ("name", "branch", "repository", "architecture"))


def normalize(records):
    packages = {}
    for record in records:
        previous = packages.setdefault(record["url"], record)
        if previous != record:
            raise ValueError(f"Conflicting package records at {record['url']}")
    ordered = sorted(
        packages.values(), key=lambda row: (row["buildTime"], row["version"]), reverse=True
    )
    ordered.sort(key=package_group)
    groups = set()
    for record in ordered:
        group = package_group(record)
        record["latest"] = group not in groups
        groups.add(group)
    return {"schemaVersion": 1, "packages": ordered}


def load_catalog():
    def load(source):
        repository, architecture = source
        host = SOURCES[repository][0]
        url = f"{host}/apk/{BRANCH}/{repository}/{architecture}/APKINDEX.tar.gz"
        try:
            return parse_index(fetch(url), repository, architecture)
        except (OSError, KeyError, ValueError, tarfile.TarError, EOFError) as error:
            raise ValueError(f"{url}: {error}") from error

    indexes = [(repository, arch) for repository, (_, arches) in SOURCES.items() for arch in arches]
    with ThreadPoolExecutor(max_workers=len(indexes)) as workers:
        return normalize(record for index in workers.map(load, indexes) for record in index)


def serialize(catalog):
    return (json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(catalog):
    return hashlib.sha256(serialize(catalog)).hexdigest()
