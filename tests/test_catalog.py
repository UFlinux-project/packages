import gzip
import io
import sys
import tarfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from catalog import digest, load_catalog, normalize, parse_index
from refresh import refresh


def stream(name, data):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        entry = tarfile.TarInfo(name)
        entry.size = len(data)
        archive.addfile(entry, io.BytesIO(data))
    return gzip.compress(buffer.getvalue())


def archive(version, timestamp, architecture="x86_64"):
    index = (
        f"C:Q1hash\nP:uflinux-test+doc\nV:{version}\nA:{architecture}\n"
        f"t:{timestamp}\nT:Test: docs\nD:so:libx.so cmd:test\n"
        "U:javascript:example\np:cmd:test=1.0\n"
    )
    return stream(".SIGN.RSA256.test", b"signature") + stream("APKINDEX", index.encode())


class CatalogTests(unittest.TestCase):
    def test_signed_index_fields_and_architecture(self):
        pkg, = parse_index(archive("1.0-r0", 42, "noarch"), "uflinux", "x86_64")
        self.assertEqual(pkg["description"], "Test: docs")
        self.assertEqual(pkg["depends"], ["so:libx.so", "cmd:test"])
        self.assertEqual(pkg["provides"], ["cmd:test=1.0"])
        self.assertEqual(pkg["packageArchitecture"], "noarch")
        self.assertEqual(pkg["projectUrl"], "")
        self.assertIn("uflinux-test%2Bdoc-1.0-r0.apk", pkg["downloadUrl"])

    def test_latest_and_digest_independent_of_input_order(self):
        older = parse_index(archive("1.0-r0", 40), "uflinux", "x86_64")
        latest = parse_index(archive("1.0-r2", 42), "uflinux", "x86_64")
        apps = parse_index(archive("1.0-r1", 41), "uflinux-apps", "x86_64")
        first = normalize(older + latest + apps)
        second = normalize(apps + latest + older)
        self.assertEqual(digest(first), digest(second))
        self.assertEqual(
            [(pkg["repository"], pkg["version"]) for pkg in first["packages"] if pkg["latest"]],
            [("uflinux", "1.0-r2"), ("uflinux-apps", "1.0-r1")],
        )

    def test_live_build_rejects_missing_or_malformed_source(self):
        for fixture in (OSError("unavailable"), b"not an index"):
            with self.subTest(fixture=fixture), patch("catalog.fetch") as get:
                if isinstance(fixture, OSError):
                    get.side_effect = fixture
                else:
                    get.return_value = fixture
                with self.assertRaisesRegex(ValueError, r"APKINDEX\.tar\.gz"):
                    load_catalog()


class RefreshTests(unittest.TestCase):
    @patch("refresh.urlopen")
    @patch("refresh.fetch")
    @patch("refresh.load_catalog")
    def test_refresh_only_on_change(self, load, fetch, post):
        load.return_value = normalize([])
        fetch.return_value = digest(load.return_value).encode()
        refresh("https://example.org", "https://example.org/hook")
        post.assert_not_called()

        fetch.return_value = b"a" * 64
        response = MagicMock(status=200)
        post.return_value.__enter__.return_value = response
        refresh("https://example.org", "https://example.org/hook")
        self.assertEqual(post.call_args.args[0].get_method(), "POST")

        post.reset_mock()
        load.side_effect = OSError("index unavailable")
        with self.assertRaises(OSError):
            refresh("https://example.org", "https://example.org/hook")
        post.assert_not_called()
