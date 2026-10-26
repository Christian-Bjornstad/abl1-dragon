import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.evidence_store import EvidenceStore
from abl1_workstation.lookup import canonical_identity
from abl1_workstation.workflow import allele_key

V={'chrom':'9','pos':133748283,'ref':'C','alt':'T','sample':'DO_NOT_STORE','email':'PRIVATE'}

class EvidenceStoreTests(unittest.TestCase):
    def test_completed_sources_survive_restart_without_sample_or_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EvidenceStore(directory)
            store.save(V,{'provider':'clinvar','identity':canonical_identity(V),'status':'found','summary':'Exact allele',
                          'identity_verified':True,'checked_at':'2026-10-26T10:00:00+00:00','password':'SECRET'})
            restored=EvidenceStore(directory).load(V)
            self.assertEqual(restored[0]['summary'],'Exact allele')
            content=''.join(p.read_text() for p in Path(directory).rglob('*.json'))
            for private in ('DO_NOT_STORE','PRIVATE','SECRET','password'):self.assertNotIn(private,content)
            self.assertEqual(store.load({**V,'alt':'G'}),[])
    def test_edited_cache_cannot_attach_another_allele_or_external_local_picture(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EvidenceStore(directory)
            store.save(V,{'provider':'clinvar','identity':canonical_identity(V),'status':'found','identity_verified':True})
            latest=Path(directory)/'evidence/databases'/allele_key(V)/'clinvar.json'
            data=json.loads(latest.read_text());data['screenshot']='C:/private/secret.png'
            latest.write_text(json.dumps(data));self.assertNotIn('screenshot',store.load(V)[0])
            data['identity']['alt']='G';latest.write_text(json.dumps(data));self.assertEqual(store.load(V),[])

if __name__=='__main__':unittest.main()
