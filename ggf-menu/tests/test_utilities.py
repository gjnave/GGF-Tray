import hashlib
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ggf_hub import File, Model, _paths, choices, download
from ggf_utilities import resource_access


class DownloadResponse(io.BytesIO):
    def __init__(self, data, status=200, bounds=None):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Range":bounds} if bounds else {}

    def geturl(self):
        return "https://huggingface.co/example/weights"


class UtilitiesTests(unittest.TestCase):
    def test_whole_shard_set_includes_matching_index(self):
        def row(name):
            return {"path":name,"type":"file","size":1,"oid":"1"*40}
        one = row("quant/model-00001-of-00002.safetensors")
        two = row("quant/model-00002-of-00002.safetensors")
        index = row("quant/model.safetensors.index.json")
        complete, = choices("fixture/model","a"*40,[two,index,one])
        self.assertEqual([f.path for f in complete.files],[one["path"],two["path"],index["path"]])
        self.assertFalse(complete.missing)
        partial, = choices("fixture/model","a"*40,[index,two])
        self.assertTrue(partial.missing)

    def test_resume_verified_content_and_preserve_conflicts(self):
        data = b"small test weights"
        record = File("quant/model.gguf",len(data),hashlib.sha256(data).hexdigest(),True)
        artifact = Model("fixture/model","a"*40,record.path,(record,))
        stop = threading.Event()
        with tempfile.TemporaryDirectory() as area:
            folder = Path(area)
            final, partial = _paths(folder,record)
            partial.write_bytes(data[:4])
            with patch("ggf_hub.urlopen_with_ssl",return_value=DownloadResponse(data[4:],206,f"bytes 4-{len(data)-1}/{len(data)}")) as opener:
                download(artifact,folder,stop,lambda *_:None)
                self.assertEqual(opener.call_args.args[0].get_header("Range"),"bytes=4-")
                self.assertIn(artifact.revision,opener.call_args.args[0].full_url)
            self.assertEqual(final.read_bytes(),data)
            with patch("ggf_hub.urlopen_with_ssl",side_effect=AssertionError("unexpected transfer")):
                cached, = download(artifact,folder,stop,lambda *_:None)
                self.assertTrue(cached.samefile(final))
                final.write_bytes(b"unrelated existing weights")
                with self.assertRaises(FileExistsError):
                    download(artifact,folder,stop,lambda *_:None)
                self.assertEqual(final.read_bytes(),b"unrelated existing weights")

    def test_wrong_range_or_hash_never_becomes_model(self):
        original=b"known weights"
        file=File("file.gguf",len(original),hashlib.sha256(original).hexdigest(),True)
        item=Model("fixture/model","a"*40,file.path,(file,))
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            final,partial=_paths(folder,file)
            partial.write_bytes(original[:2])
            with patch("ggf_hub.urlopen_with_ssl",return_value=DownloadResponse(original,206,"bytes 0-11/12")):
                with self.assertRaisesRegex(ValueError,"range"):
                    download(item,folder,threading.Event(),lambda *_:None)
            self.assertEqual(partial.read_bytes(),original[:2])
            with patch("ggf_hub.urlopen_with_ssl",return_value=DownloadResponse(original[:2]+b"x"*(len(original)-2))):
                with self.assertRaisesRegex(ValueError,"verification failed"):
                    download(item,folder,threading.Event(),lambda *_:None)
            self.assertFalse(final.exists())

    def test_resource_access_uses_current_account_and_fails_closed(self):
        account=Mock(cached_auth={"token":"fixture","tier":"rancher"})
        account.check_token.return_value={"tier":"free"}
        self.assertEqual(resource_access(account),"locked")
        account.check_token.return_value=None
        self.assertEqual(resource_access(account),"unverified")
        for tier in ("prairie-dog","farm-hand","rancher","gunslinger"):
            account.check_token.return_value={"tier":tier}
            self.assertEqual(resource_access(account),"paid")
        account.check_token.return_value={"tier":"unexpected"}
        self.assertEqual(resource_access(account),"locked")
        account.cached_auth={}
        self.assertEqual(resource_access(account),"guest")

