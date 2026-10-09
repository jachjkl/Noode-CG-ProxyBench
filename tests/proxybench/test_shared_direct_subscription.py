import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.io_utils import atomic_write_bytes
from core.proxybench.export import DIRECT_SUBSCRIPTION, publish
from scripts.proxybench_channel import pack, unpack
from tests.proxybench.test_dual_methods import records


class SharedDirectSubscriptionTests(unittest.TestCase):
    def test_tcp_and_tls_use_one_subscription_with_saved_100_200_300_and_jp_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=root/"output/Nodes-TCP"
            (root/"output").mkdir()
            proxy=root/"output/nodes.txt"
            proxy.write_bytes(b"proxy last good")
            for probe,ordinary,japanese in [("tcp",100,10),("tls",200,7),("tcp",300,0)]:
                rows=records(ordinary,japanese,"tcp_tls")
                for row in rows:
                    row["latency_probe"]=probe
                report=publish(output,rows,{"measurement_mode":"tcp_tls","publication_limits":{"general":ordinary,"japan":japanese}})
                self.assertTrue(report["published"])
                self.assertEqual((root/DIRECT_SUBSCRIPTION).read_bytes(),(output/"nodes.txt").read_bytes())
                self.assertEqual(len((root/DIRECT_SUBSCRIPTION).read_text().splitlines()),ordinary+japanese)
                self.assertEqual(proxy.read_bytes(),b"proxy last good")
            prior=(root/DIRECT_SUBSCRIPTION).read_bytes()
            publish(output,[],{"measurement_mode":"tcp_tls","status":"failed"})
            self.assertEqual((root/DIRECT_SUBSCRIPTION).read_bytes(),prior)

    def test_cloud_validates_shared_file_before_writes_and_upgrades_legacy_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            local,cloud=root/"local",root/"cloud"
            publish(local/"output/Nodes-TCP",records(200,7,"tcp_tls"),{"measurement_mode":"tcp_tls","publication_limits":{"general":200,"japan":7}})
            content=pack(local,"result","tcp_tls")
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                files={name:package.read(name) for name in package.namelist()}
            self.assertEqual(files[DIRECT_SUBSCRIPTION],files["output/Nodes-TCP/nodes.txt"])
            def archive(items):
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,"w") as package:
                    for name,data in items.items():
                        package.writestr(name,data)
                return stream.getvalue()
            bad=archive({**files,DIRECT_SUBSCRIPTION:b"82.139.242.5:443#DE\n"})
            with self.assertRaisesRegex(ValueError,"共享文件"):
                unpack(bad,hashlib.sha256(bad).hexdigest(),cloud,"result")
            self.assertFalse(cloud.exists())
            old=archive({name:data for name,data in files.items() if name!=DIRECT_SUBSCRIPTION})
            unpack(old,hashlib.sha256(old).hexdigest(),cloud,"result")
            self.assertEqual((cloud/DIRECT_SUBSCRIPTION).read_bytes(),files[DIRECT_SUBSCRIPTION])
            proxy=cloud/"output/nodes.txt"
            proxy.write_bytes(b"unchanged proxy")
            unpack(content,hashlib.sha256(content).hexdigest(),cloud,"result")
            self.assertEqual(proxy.read_bytes(),b"unchanged proxy")

    def test_shared_file_write_failure_rolls_back_metadata_and_both_text_views(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            output=root/"output/Nodes-TCP"
            publish(output,records(100,10,"tcp_tls"),{"measurement_mode":"tcp_tls"})
            before={str(p.relative_to(root)):p.read_bytes() for p in (root/"output").rglob("*") if p.is_file()}
            failed=False
            def write(path,data):
                nonlocal failed
                if path==root/DIRECT_SUBSCRIPTION and not failed:
                    failed=True
                    raise OSError("fixture failed shared-file write")
                atomic_write_bytes(path,data)
            with patch("core.proxybench.export.atomic_write_bytes",side_effect=write),self.assertRaises(OSError):
                publish(output,records(200,7,"tcp_tls"),{"measurement_mode":"tcp_tls","publication_limits":{"general":200,"japan":7}})
            after={str(p.relative_to(root)):p.read_bytes() for p in (root/"output").rglob("*") if p.is_file()}
            self.assertEqual(before,after)
            self.assertEqual(len(json.loads((output/"nodes.json").read_text())),110)
