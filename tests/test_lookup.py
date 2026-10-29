"""Database responses are synthetic; no credentials or network are needed."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from urllib.error import HTTPError, URLError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.lookup import LookupService, canonical_identity, variant_key

VARIANT={'assembly':'GRCh37','chrom':'chr9','pos':133748283,'ref':'C','alt':'T',
         'cdna':'c.944C>T','protein_snv_alone':'p.T315I','sample':'NEVER_SEND_SAMPLE'}


def clinvar_xml(ref='C',alt='T',assembly='GRCh37',wrapper='SimpleAllele'):
    allele=f'<SimpleAllele><Location><SequenceLocation Assembly="{assembly}" Chr="9" positionVCF="133748283" referenceAlleleVCF="{ref}" alternateAlleleVCF="{alt}"/></Location></SimpleAllele>'
    if wrapper!='SimpleAllele':allele='<'+wrapper+'>'+allele+'</'+wrapper+'>'
    return (f'<VariationArchive Accession="VCV000000123" Version="2" VariationID="123" VariationName="Synthetic variant"><RecordStatus>current</RecordStatus><ClassifiedRecord>{allele}<Classifications>'
            '<GermlineClassification><ReviewStatus>reviewed by expert panel</ReviewStatus><Description>Pathogenic</Description></GermlineClassification>'
            '<SomaticClinicalImpact><ReviewStatus>criteria provided</ReviewStatus><Description>Tier II</Description></SomaticClinicalImpact>'
            '</Classifications><RCVList><ClinicalSignificance><Description>Do not inherit RCV</Description></ClinicalSignificance></RCVList></ClassifiedRecord></VariationArchive>').encode()


class FakeTransport:
    def __init__(self,*responses):self.responses=list(responses);self.calls=[]
    def __call__(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs))
        item=self.responses.pop(0)
        if isinstance(item,Exception):raise item
        return item if isinstance(item,bytes) else json.dumps(item).encode()


class LookupTests(unittest.TestCase):
    def test_clinvar_reference_sequences_belong_only_to_the_exact_simple_allele(self):
        references=('<HGVSlist><HGVS><NucleotideExpression sequenceAccessionVersion="NM_005157.6">'
                    '<Expression>NM_005157.6(ABL1):c.944C&gt;T</Expression></NucleotideExpression>'
                    '<ProteinExpression sequenceAccessionVersion="NP_005148.2"><Expression>NP_005148.2:p.Thr315Ile</Expression>'
                    '</ProteinExpression></HGVS></HGVSlist>')
        xml=clinvar_xml().replace(b'</SimpleAllele>',references.encode()+b'</SimpleAllele>')
        unrelated=clinvar_xml(alt='G').replace(b'</SimpleAllele>',b'<HGVSlist><HGVS><Expression>NM_999999.9:c.1A&gt;G</Expression></HGVS></HGVSlist></SimpleAllele>')
        result,_=self.clinvar(b'<ReleaseSet>'+unrelated+xml+b'</ReleaseSet>')
        self.assertEqual(result['transcripts'],['NM_005157.6'])
        self.assertEqual(result['proteins'],['NP_005148.2'])
        self.assertEqual(result['reference_hgvs'],['NM_005157.6(ABL1):c.944C>T','NP_005148.2:p.Thr315Ile'])

    def test_browser_reference_sequences_survive_service_projection(self):
        class Adapter:
            def lookup(self,provider,variant,**kwargs):
                return {'status':'found','identity':canonical_identity(variant),'summary':'Exact',
                        'transcripts':['NM_005157.6'],'proteins':['NP_005148.2'],
                        'reference_hgvs':['NM_005157.6:c.944C>T']}
        service,_=self.service(browser_adapter=Adapter())
        result=service.lookup(VARIANT,['franklin'],settings={'provider_modes':{'franklin':'browser'}})[0]
        self.assertEqual(result['transcripts'],['NM_005157.6'])
        self.assertEqual(result['proteins'],['NP_005148.2'])
        self.assertEqual(result['reference_hgvs'],['NM_005157.6:c.944C>T'])
    def test_closed_portal_failure_does_not_lose_other_provider_results(self):
        class Adapter:
            def lookup(self,*args,**kwargs):raise RuntimeError('private session diagnostic')
        service,_=self.service({'esearchresult':{'count':'0','idlist':[]}},browser_adapter=Adapter())
        results=service.lookup(VARIANT,['franklin','clinvar'],settings={'provider_modes':{'franklin':'browser'}})
        self.assertEqual([r['status'] for r in results],['error','not_found'])
        self.assertNotIn('private session diagnostic',str(results))
    def setUp(self):self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()
    def service(self,*responses,**kwargs):
        transport=FakeTransport(*responses)
        return LookupService(Path(self.tmp.name),transport=transport,**kwargs),transport
    def clinvar(self,xml,variant=None):
        service,transport=self.service({'esearchresult':{'count':'1','idlist':['123']}},xml)
        return service.lookup(variant or VARIANT,['clinvar'])[0],transport

    def test_clinvar_exact_allele_retains_classification_axes_without_rcv_inheritance(self):
        result,transport=self.clinvar(clinvar_xml())
        self.assertEqual(result['status'],'found');self.assertEqual(result['accession'],'VCV000000123.2')
        self.assertEqual(result['classifications']['germline']['description'],'Pathogenic')
        self.assertEqual(result['classifications']['somatic_clinical_impact']['description'],'Tier II')
        self.assertIsNone(result['classifications']['oncogenicity'])
        self.assertNotIn('Do not inherit',str(result));self.assertNotIn('NEVER_SEND_SAMPLE',str(transport.calls))
        self.assertEqual(result['variant_key'],variant_key(VARIANT))

    def test_clinvar_wrong_build_or_allele_never_becomes_found(self):
        for xml in (clinvar_xml(alt='G'),clinvar_xml(assembly='GRCh38')):
            result,_=self.clinvar(xml)
            self.assertEqual(result['status'],'not_found');self.assertEqual(result['classification'],'')

    def test_haplotype_component_cannot_inherit_whole_record_or_single_base_evidence(self):
        result,_=self.clinvar(clinvar_xml(wrapper='Haplotype'))
        self.assertEqual(result['status'],'not_found')
        result,_=self.clinvar(clinvar_xml(),dict(VARIANT,ref='CT',alt='TG'))
        self.assertEqual(result['status'],'not_found')

    def test_no_candidate_is_not_found_but_search_payload_error_is_error(self):
        service,_=self.service({'esearchresult':{'count':'0','idlist':[]}})
        self.assertEqual(service.lookup(VARIANT,['clinvar'])[0]['status'],'not_found')
        service,_=self.service({'error':'unavailable'})
        self.assertEqual(service.lookup(VARIANT,['clinvar'])[0]['status'],'error')

    def test_network_errors_never_become_negative_results_or_leak_exception_secrets(self):
        service,_=self.service(URLError('token=SHOULD_NOT_LEAK'))
        result=service.lookup(VARIANT,['clinvar'])[0]
        self.assertEqual(result['status'],'error');self.assertNotIn('SHOULD_NOT_LEAK',str(result))

    def test_wrong_response_shapes_fail_per_provider_without_aborting_other_sources(self):
        service,_=self.service([],[])
        results=service.lookup(VARIANT,['clinvar','oncokb'],tokens={'oncokb':'test'})
        self.assertEqual([r['status'] for r in results],['error','error'])







    def test_oncokb_uses_genomic_query_and_token_header_without_echoing_credentials(self):
        response={'query':{'hgvs':'9:g.133748283C>T','referenceGenome':'GRCh37'},'variantExist':True,
                  'oncogenic':'Oncogenic','highestResistanceLevel':'LEVEL_R1','mutationEffect':{'knownEffect':'Gain-of-function'}}
        service,transport=self.service(response);result=service.lookup(VARIANT,['oncokb'],tokens={'oncokb':'TEST_TOKEN'})[0]
        self.assertEqual(result['status'],'found');self.assertEqual(result['classification'],'Oncogenic')
        self.assertIn('LEVEL_R1',result['evidence_level']);self.assertNotIn('TEST_TOKEN',str(result))
        self.assertEqual(transport.calls[0][2]['headers']['Authorization'],'Bearer TEST_TOKEN')
        self.assertEqual(transport.calls[0][2]['params']['hgvsg'],'9:g.133748283C>T')

    def test_oncokb_different_query_is_error_and_auth_states_are_explicit(self):
        service,_=self.service({'query':{'hgvs':'9:g.133748283C>G','referenceGenome':'GRCh37'},'variantExist':True})
        self.assertEqual(service.lookup(VARIANT,['oncokb'],tokens={'oncokb':'test'})[0]['status'],'error')
        service,transport=self.service()
        self.assertEqual(service.lookup(VARIANT,['oncokb'])[0]['status'],'license_required');self.assertEqual(transport.calls,[])
        for code,status in ((401,'login_required'),(403,'license_required'),(429,'error')):
            service,_=self.service(HTTPError('https://example.invalid',code,'synthetic',{},None))
            self.assertEqual(service.lookup(VARIANT,['oncokb'],tokens={'oncokb':'test'})[0]['status'],status)

    def test_franklin_only_accepts_explicit_matching_build_and_alleles(self):
        record={'variant':{'chromosome':'chr9','start_position':133748283,'ref':'C','alt':'T','reference_genome':'hg19'},
                'classification':{'acmg_classification':'Pathogenic'},'variant_franklin_link':'https://franklin.genoox.com/clinical-db/variant/snp/chr9-133748283-C-T'}
        service,_=self.service({'variants':[record]})
        result=service.lookup(VARIANT,['franklin'],tokens={'franklin':'test'})[0]
        self.assertEqual(result['status'],'found');self.assertIn('Pathogenic',result['classification'])
        record['variant']['alt']='G';service,_=self.service({'variants':[record]})
        self.assertEqual(service.lookup(VARIANT,['franklin'],tokens={'franklin':'test'})[0]['status'],'not_found')

    def test_browser_adapter_receives_only_sanitized_identity_and_found_requires_exact_match(self):
        class Adapter:
            def lookup(self,provider,variant,**kwargs):
                self.variant=variant
                return {'status':'found','identity':canonical_identity(variant),'classification':'Synthetic portal class','summary':'Synthetic result'}
        adapter=Adapter();service,_=self.service(browser_adapter=adapter)
        result=service.lookup(VARIANT,['franklin'],settings={'provider_modes':{'franklin':'browser'}})[0]
        self.assertEqual(result['status'],'found');self.assertNotIn('sample',adapter.variant)
        self.assertNotIn('gene',adapter.variant)
        self.assertNotIn('NEVER_SEND_SAMPLE',str(result))
        adapter.lookup=lambda *args,**kwargs:{'status':'found','summary':'unverified page'}
        self.assertEqual(service.lookup(VARIANT,['franklin'],settings={'provider_modes':{'franklin':'browser'}})[0]['status'],'error')

    def test_invalid_alleles_or_build_never_start_network(self):
        for variant in (dict(VARIANT,assembly='GRCh38'),dict(VARIANT,alt='<DEL>'),dict(VARIANT,pos=0)):
            service,transport=self.service()
            result=service.lookup(variant,['clinvar'])[0]
            self.assertEqual(result['status'],'unsupported');self.assertEqual(transport.calls,[])

    def test_default_mtbp_has_no_remote_report_side_effects(self):
        service,transport=self.service();result=service.lookup(VARIANT,['mtbp'])[0]
        self.assertEqual(result['status'],'license_required');self.assertEqual(transport.calls,[])


if __name__=='__main__':unittest.main()
