"""Exact-allele source selection; no remote requests or clinical classification."""
from urllib.parse import quote, urlsplit
import re
from .models import codon315

ALLELES={
    'ATG':(133748283,'CT','TG','c.944_945delinsTG','p.T315M','ATG · T315M, samlet allel'),
    'ATT':(133748283,'C','T','c.944C>T','p.T315I','ATT · T315I'),
    'CTT':(133748282,'AC','CT','c.943_944delinsCT','p.T315L','CTT · kandidat T315L'),
}


def allele_options(v,phase):
    values=[('vcf','Valgt VCF-komponent, én SNV alene')]
    if v and codon315(v):
        observed={r['haplotype'] for r in phase if r.get('sample')==v['sample'] and r.get('filter')=='BQ30_MQ20' and r.get('fragments',0)>0}
        values += [(key,row[5]) for key,row in ALLELES.items() if key in observed]
    return values


def source_allele(v,scope,phase):
    if not v:return None
    if scope not in {key for key,_ in allele_options(v,phase)} or scope=='vcf':return v
    pos,ref,alt,cdna,protein,_=ALLELES[scope]
    return {**v,'pos':pos,'ref':ref,'alt':alt,'cdna':cdna,'protein_snv_alone':protein}


def exact_evidence(records,v):
    if not v:return []
    return [r for r in records if r.get('identity',{}).get('assembly')=='GRCh37' and str(r['identity'].get('chrom')).removeprefix('chr')==str(v.get('chrom')).removeprefix('chr') and r['identity'].get('pos')==v.get('pos') and r['identity'].get('ref')==v.get('ref') and r['identity'].get('alt')==v.get('alt')]


def provider_url(provider,v):
    v=v or {};target=str(v.get('chrom','')).removeprefix('chr')=='9' and bool(v.get('cdna') or v.get('codon') or v.get('bed_name'))
    generic=not v.get('pos') or (provider.get('queryKind') in ('gene','search') and not target)
    template=provider.get('home') if generic else provider.get('queryTemplate') or provider.get('home')
    if not template:return None
    fields={'chrom':str(v.get('chrom','')).removeprefix('chr'),'pos':v.get('pos',''),'ref':v.get('ref',''),'alt':v.get('alt',''),'gene':'ABL1','protein':str(v.get('protein_snv_alone') or '').removeprefix('p.'),'cdna':v.get('cdna') or ''}
    url=re.sub(r'\{(\w+)\}',lambda m:quote(str(fields.get(m[1],'')),safe=''),template)
    parsed=urlsplit(url)
    return url if parsed.scheme=='https' and parsed.hostname and not parsed.username else None
