import gzip,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.reference_bundle import prepare_reference,bundled_reference
from unittest.mock import patch

class ReferenceBundleTests(unittest.TestCase):
    def fixture(self,root):
        bundle=root/'assets';bundle.mkdir()
        raw=b'>chr9\nACGTN\n';compressed=gzip.compress(raw,mtime=0);index=b'chr9\t5\t6\t5\t6\n'
        (bundle/'chr9.fa.gz').write_bytes(compressed);(bundle/'chr9.fa.fai').write_bytes(index)
        metadata={'assembly':'GRCh37','chromosome':'chr9','length':5,'sequence_md5':hashlib.md5(b'ACGTN').hexdigest(),
                  'fasta_bytes':len(raw),'fasta_sha256':hashlib.sha256(raw).hexdigest(),'gzip_sha256':hashlib.sha256(compressed).hexdigest(),'index_sha256':hashlib.sha256(index).hexdigest()}
        (bundle/'manifest.json').write_text(json.dumps(metadata));return bundle,raw
    def test_offline_expand_and_repeat_without_any_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,raw=self.fixture(root);destination=root/'cache'
            result=prepare_reference(bundle,destination)
            self.assertEqual(result.read_bytes(),raw);self.assertTrue(Path(str(result)+'.fai').is_file())
            stamp=result.stat().st_mtime_ns
            self.assertEqual(prepare_reference(bundle,destination),result);self.assertEqual(result.stat().st_mtime_ns,stamp)
    def test_corrupt_source_never_publishes_partial_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,_=self.fixture(root);(bundle/'chr9.fa.gz').write_bytes(b'BROKEN')
            with self.assertRaises(ValueError):prepare_reference(bundle,root/'cache')
            self.assertFalse((root/'cache/chr9.fa').exists())
    def test_altered_index_is_rejected_and_corrupt_cache_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,raw=self.fixture(root);destination=root/'cache'
            result=prepare_reference(bundle,destination);result.write_bytes(b'CORRUPT')
            self.assertEqual(prepare_reference(bundle,destination).read_bytes(),raw)
            (bundle/'chr9.fa.fai').write_text('wrong index')
            with self.assertRaises(ValueError):prepare_reference(bundle,destination)
    def test_manifest_expansion_limit_prevents_gzip_bomb_or_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,_=self.fixture(root)
            data=json.loads((bundle/'manifest.json').read_text());data['fasta_bytes']=4
            (bundle/'manifest.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError):prepare_reference(bundle,root/'cache')
            self.assertFalse((root/'cache/chr9.fa').exists())

    def test_read_only_program_folder_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,_=self.fixture(root)
            (root/'assets/reference').mkdir();(bundle/'manifest.json').replace(root/'assets/reference/manifest.json')
            expected=root/'state/reference/hg19/chr9.fa'
            with patch('abl1_workstation.reference_bundle.prepare_reference',side_effect=[PermissionError(),expected]) as prepare:
                self.assertEqual(bundled_reference(root,root/'state'),expected)
                self.assertEqual(prepare.call_args.args[1],expected.parent)

    def test_settings_replace_missing_external_path_with_offline_bundle(self):
        from abl1_workstation.settings import Settings
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundle,raw=self.fixture(root)
            bundle.rename(root/'temporary-assets');(root/'assets').mkdir()
            (root/'temporary-assets').rename(root/'assets/reference')
            state=root/'state';state.mkdir()
            (state/'settings.json').write_text(json.dumps({'reference':str(root/'missing.fa')}))
            with patch('abl1_workstation.settings.resource_root',return_value=root):
                settings=Settings(state)
            self.assertEqual(settings.reference,str(root/'reference/hg19/chr9.fa'))
            self.assertEqual(Path(settings.reference).read_bytes(),raw)

    def test_checked_in_bundle_is_complete_hg19_chr9(self):
        from abl1_workstation.igv_live import inspect_reference,verify_reference
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            reference=prepare_reference(root/'assets/reference',Path(temp))
            info=inspect_reference(reference)
            self.assertEqual(info.length,141213431)
            self.assertEqual(verify_reference(info),'3e273117f15e0a400f01055d9f393768')

if __name__=='__main__':unittest.main()
