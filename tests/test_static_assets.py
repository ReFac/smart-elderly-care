from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from server import Handler


class StaticAssetTests(unittest.TestCase):
    def request(self, path, validator=""):
        handler = Handler.__new__(Handler)
        handler.headers = {"Host": "localhost", "If-None-Match": validator}
        handler.path = path
        handler.update_gate = handler.public_origin = None
        handler.store = Mock()
        handler.store.rounds.matches.return_value = False
        handler.store.photo.return_value = (b"medical", "image/png")
        handler.send_response = Mock()
        headers = {}
        handler.send_header = headers.__setitem__
        handler.end_headers = Mock()
        handler.wfile = BytesIO()
        handler.dispatch("GET")
        return handler.send_response.call_args.args[0], headers, handler.wfile.getvalue()

    def test_code_assets_revalidate_and_notice_replacement_with_same_size_and_mtime(self):
        with TemporaryDirectory() as directory, patch("server.WEB", Path(directory)):
            for filename in ("app.js", "style.css"):
                with self.subTest(filename=filename):
                    asset = Path(directory) / filename
                    asset.write_bytes(b"first")
                    status, headers, content = self.request("/" + filename)
                    self.assertEqual((status, content), (200, b"first"))
                    self.assertEqual(headers["Cache-Control"], "private, no-cache")
                    tag = headers["ETag"]
                    for validator in (tag, '"old", ' + tag.removeprefix("W/"), "*"):
                        status, headers, content = self.request("/" + filename, validator)
                        self.assertEqual((status, content, headers["ETag"]), (304, b"", tag))
                        self.assertNotIn("Content-Length", headers)
                    replacement = asset.with_suffix(".new")
                    replacement.write_bytes(b"other")
                    stat = asset.stat()
                    os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                    replacement.replace(asset)
                    status, headers, content = self.request("/" + filename, tag)
                    self.assertEqual((status, content), (200, b"other"))
                    self.assertNotEqual(headers["ETag"], tag)

    def test_page_and_medical_images_keep_no_store_even_with_validator(self):
        for path in ("/?workspace=1", "/api/documents/doc1/image"):
            with self.subTest(path=path):
                status, headers, content = self.request(path, "*")
                self.assertEqual(status, 200)
                self.assertTrue(content)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertNotIn("ETag", headers)
