import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.lookup import LookupService,canonical_identity

V={'assembly':'GRCh37','chrom':'9','pos':133748283,'ref':'C','alt':'T','cdna':'c.944C>T'}

class CosmicResolutionTests(unittest.TestCase):
    def test_portal_uses_exact_mutation_record_instead_of_first_generic_search_link(self):
        fields={'MutationID':['COSM12560'],'GeneName':['ABL1'],'MutationCDS':['c.944C>T'],
                'MutationAA':['p.T315I'],'MutationGenomePosition':['9:133748283-133748283'],
                'MutationStrand':['+'],'GRChVer':['37'],'AccessionNumber':['NM_005157.6'],'PubmedPMID':['']}
        adapter=Mock();adapter.lookup.return_value={'status':'found','identity':canonical_identity(V),'identity_verified':True}
        with tempfile.TemporaryDirectory() as folder:
            service=LookupService(folder,transport=Mock(side_effect=lambda *a,**k:json.dumps([1,['COSM12560'],fields]).encode()),browser_adapter=adapter)
            self.assertEqual(service.lookup(V,['cosmic'],settings={'provider_modes':{'cosmic':'browser'}})[0]['status'],'found')
            settings=adapter.lookup.call_args.kwargs['settings']
            self.assertEqual(settings['cosmic_mutation_id'],'12560')
            fields['MutationCDS']=['c.944C>G']
            service.lookup(V,['cosmic'],settings={'provider_modes':{'cosmic':'browser'}})
            self.assertNotIn('cosmic_mutation_id',adapter.lookup.call_args.kwargs['settings'])

if __name__=='__main__':unittest.main()
