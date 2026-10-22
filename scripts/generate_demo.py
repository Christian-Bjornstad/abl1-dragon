"""Rebuild an explicitly invented public demonstration. No clinical inputs."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from abl1_workstation.domain import validate_package

def main():
    identities=[('DEMO-A',133748283,'C','T',0.12,1000,880,120),('DEMO-A',133748284,'T','G',0.07,1000,930,70),('DEMO-B',133738330,'A','G',0.25,24,18,6)]
    rows=[]
    for line,(sample,pos,ref,alt,af,dp,ref_ad,alt_ad) in enumerate(identities,1):
        rows.append({'sample':sample,'chrom':'chr9','pos':pos,'ref':ref,'alt':alt,'filter':'PASS','format_af':af,'format_dp':dp,'ref_ad':ref_ad,'alt_ad':alt_ad,'info_dp':dp,'sq':None,'notes':'Oppdiktet demonstrasjonsrad. Ingen prøve, sekvensering eller klinisk forventning ligger bak.','source':'synthetic_demo','source_line':line,'sample_has_alt':True})
    data={'schema_version':1,'mode':'synthetic_demo','date':None,'genome':'hg19/GRCh37','transcript':'NM_005157.6','protein':'NP_005148.2','metadata':{'assembly':'GRCh37','synthetic_demo':True,'data_origin':'Invented from public allele identities; not measured sequencing results','clinical_validation':False},'samples':[{'sample':name,'expected':'Ingen klinisk forventning – syntetisk demonstrasjon','status':'Konstruerte tall; ingen biologisk eller klinisk konklusjon','note':'Demonstrerer programfunksjoner, ikke metodeytelse.'} for name in ('DEMO-A','DEMO-B')],'variants':rows,'qc':[],'phase_rows':[],'read_rows':[],'sources':[],'intervals':[],'bed':[],'totals':{'records':3,'passed':3,'filtered':0,'snv':3,'insertions':0,'deletions':0},'provenance':{'source':'scripts/generate_demo.py','data_origin':'All sample labels and quantitative values are invented. Public reference coordinates illustrate SNV annotation only.','clinical_inputs_used':False,'alignment_files_used':False}}
    output=ROOT/'desktop/data/pilot.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(validate_package(data),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Generated 2 explicitly synthetic labels and 3 invented VCF components; no QC, reads, phase or clinical history.')

if __name__=='__main__':main()
