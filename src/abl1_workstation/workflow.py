"""Technical candidate sorting, independent of clinical interpretation."""
import hashlib
import json


def allele_key(variant):
    identity=['GRCh37',str(variant.get('chrom','')).removeprefix('chr'),
              variant.get('pos'),variant.get('ref'),variant.get('alt')]
    return hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()


def row_key(variant):
    return hashlib.sha256((str(variant.get('sample',''))+'\0'+allele_key(variant)).encode()).hexdigest()


def category(v):
    if v.get('reference_match') is False:return 'REF-avvik'
    if v.get('normal_transcript_continuation'):return 'Transkriptfortsettelse'
    if not v.get('cdna') or v.get('reference_match') is not True:return 'Øvrige'
    if v.get('sample_has_alt') is False:return 'Øvrige'
    if v.get('filter')=='PASS':return 'PASS'
    # Observable coding alleles remain inspectable regardless of exploratory AF.
    if v.get('alt_ad') is not None and v['alt_ad']>0:return 'Kontroll'
    return 'Øvrige'


def candidate_rows(rows):
    return [v for v in rows if category(v) in ('PASS','Kontroll')]
