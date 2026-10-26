"""Selected-allele database retrieval; credentials and sample data are not persisted.

Protocols follow NCBI E-utilities, gnomAD's public GraphQL API and the
API/browser lanes used by Archer-prosess. A site login is not API authorization.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

PROVIDERS=('clinvar','gnomad','cosmic','oncokb','franklin','mtbp')
STATUSES={'found','not_found','login_required','license_required','error','unsupported'}
HOMES={'clinvar':'https://www.ncbi.nlm.nih.gov/clinvar/',
       'gnomad':'https://gnomad.broadinstitute.org/',
       'cosmic':'https://cancer.sanger.ac.uk/cosmic/',
       'oncokb':'https://www.oncokb.org/',
       'franklin':'https://franklin.genoox.com/clinical-db/home','mtbp':'https://mtbp.org/'}
MAX_RESPONSE=8*1024*1024


def canonical_identity(variant):
    """Only assembly and VCF allele identity may be used in network queries."""
    assembly=variant.get('assembly',variant.get('reference_build','GRCh37'))
    if assembly=='hg19':assembly='GRCh37'
    chrom=str(variant.get('chrom','')).removeprefix('chr').upper()
    raw_pos=variant.get('pos')
    if isinstance(raw_pos,bool):raise ValueError('Krever en 1-basert variantposisjon.')
    try:pos=int(raw_pos)
    except (ValueError,TypeError):raise ValueError('Krever en 1-basert variantposisjon.') from None
    ref=str(variant.get('ref','')).upper();alt=str(variant.get('alt','')).upper()
    if (assembly!='GRCh37' or chrom not in {str(i) for i in range(1,23)}|{'X','Y','MT'}
            or pos<1 or str(raw_pos)!=str(pos) or not re.fullmatch('[ACGT]{1,1000}',ref)
            or not re.fullmatch('[ACGT]{1,1000}',alt) or ref==alt):
        raise ValueError('Oppslag krever GRCh37 og eksplisitt VCF-posisjon, REF og ALT.')
    return {'assembly':assembly,'chrom':chrom,'pos':pos,'ref':ref,'alt':alt}


def variant_key(variant):
    return hashlib.sha256(json.dumps(canonical_identity(variant),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def genomic_hgvs(variant):
    v=canonical_identity(variant);pos=v['pos'];ref=v['ref'];alt=v['alt']
    while ref and alt and ref[-1]==alt[-1]:ref=ref[:-1];alt=alt[:-1]
    while ref and alt and ref[0]==alt[0]:ref=ref[1:];alt=alt[1:];pos+=1
    prefix=v['chrom']+':g.'
    if not ref:return prefix+f'{pos-1}_{pos}ins{alt}'
    end=pos+len(ref)-1;coordinate=str(pos) if end==pos else f'{pos}_{end}'
    if not alt:return prefix+coordinate+'del'
    if len(ref)==len(alt)==1:return prefix+f'{pos}{ref}>{alt}'
    return prefix+coordinate+'delins'+alt


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        # Never forward a licensed API token to another host or login portal.
        raise HTTPError(req.full_url,code,'Unexpected API redirect',headers,None)


class HttpTransport:
    _lock=threading.Lock()
    _last={}
    def __init__(self,timeout=20):self.timeout=timeout
    def __call__(self,method,url,*,params=None,body=None,headers=None):
        host=urlsplit(url).hostname
        allowed={'eutils.ncbi.nlm.nih.gov','gnomad.broadinstitute.org','clinicaltables.nlm.nih.gov','www.oncokb.org','api.genoox.com'}
        if urlsplit(url).scheme!='https' or host not in allowed:raise ValueError('Ukjent database-API.')
        delay=0.42 if host=='eutils.ncbi.nlm.nih.gov' else 6.2 if host=='gnomad.broadinstitute.org' else 0
        with self._lock:
            wait=delay-(time.monotonic()-self._last.get(host,0))
            if wait>0:time.sleep(wait)
            self._last[host]=time.monotonic()
        if params:url+='?'+urlencode(params)
        request_headers={'Accept':'application/json, application/xml','User-Agent':'ABL1-Dragon/0.5 selected-allele-lookup'}
        request_headers.update(headers or {})
        raw=None
        if body is not None:raw=json.dumps(body,separators=(',',':')).encode();request_headers['Content-Type']='application/json'
        request=Request(url,data=raw,headers=request_headers,method=method)
        with build_opener(_NoRedirect()).open(request,timeout=self.timeout) as response:
            raw=response.read(MAX_RESPONSE+1)
            if len(raw)>MAX_RESPONSE:raise ValueError('Databasesvaret er for stort.')
            return raw


def _json(raw):
    value=json.loads(raw)
    if not isinstance(value,(dict,list)):raise ValueError('Uventet databasesvar.')
    return value


def _xml(raw):
    if b'<!ENTITY' in raw.upper():raise ValueError('XML-entiteter er ikke tillatt.')
    root=ET.fromstring(raw)
    for node in root.iter():node.tag=node.tag.rsplit('}',1)[-1]
    return root


class LookupService:
    def __init__(self,settings_dir,*,transport=None,browser_adapter=None):
        self.settings_dir=Path(settings_dir)
        self.transport=transport or HttpTransport()
        self.browser_adapter=browser_adapter

    @staticmethod
    def _result(provider,identity,status,summary,**details):
        return {'provider':provider,'status':status,'summary':summary,'classification':'','evidence_level':'',
                'accession':'','url':HOMES.get(provider,''),'checked_at':datetime.now(timezone.utc).isoformat(),
                'variant_key':variant_key(identity) if identity else '', 'identity':identity,**details}

    def lookup(self,variant,providers=('clinvar','gnomad'),*,tokens=None,settings=None,progress=None,browser_adapter=None):
        """Fetch only the selected public allele; tokens live in this call only.

        Optional portal adapter contract: .lookup(provider, sanitized_variant,
        settings=...) -> result dict. A found result must return exact identity.
        """
        providers=list(dict.fromkeys(str(p).lower() for p in providers))
        try:identity=canonical_identity(variant)
        except ValueError as error:return [self._result(p,None,'unsupported',str(error)) for p in providers]
        sanitized=dict(identity)
        for field in ('cdna','protein_snv_alone','gene'):
            text=variant.get(field)
            if isinstance(text,str) and len(text)<200 and not any(ord(c)<32 for c in text):sanitized[field]=text
        if ('gene' not in sanitized and identity['chrom']=='9' and variant.get('reference_match') is True
                and sanitized.get('cdna')):sanitized['gene']='ABL1'
        settings=settings or {};tokens=tokens or {};results=[]
        for provider in providers:
            if progress:progress(provider)
            try:
                if provider not in PROVIDERS:result=self._result(provider,identity,'unsupported','Kilden har ingen oppslagsadapter.')
                elif settings.get('provider_modes',{}).get(provider)=='browser':
                    result=self._browser(provider,sanitized,settings,browser_adapter or self.browser_adapter)
                else:result=getattr(self,'_'+provider)(sanitized,tokens,settings)
            except HTTPError as error:
                code=error.code;error.close()
                status='login_required' if code==401 else 'license_required' if code==403 else 'error'
                summary='Kilden krever ny innlogging.' if status=='login_required' else 'Kilden avviser tilgangen; kontroller lisens og innlogging.' if status=='license_required' else 'Kilden begrenset forespørsler; prøv senere.' if code==429 else f'Databaseforespørsel feilet (HTTP {code}).'
                result=self._result(provider,identity,status,summary)
            except (URLError,TimeoutError,ConnectionError,OSError):result=self._result(provider,identity,'error','Databasen kunne ikke nås. Kontroller nettverk/proxy og prøv igjen.')
            except RuntimeError:result=self._result(provider,identity,'error','Portalvinduet kunne ikke brukes. Åpne kilden på nytt under Innstillinger.')
            except (ValueError,TypeError,KeyError,ET.ParseError):result=self._result(provider,identity,'error','Databasesvaret kunne ikke valideres. Ingen klassifikasjon ble brukt.')
            results.append(result)
        return results

    def _browser(self,provider,v,settings,adapter):
        if adapter is None:return self._result(provider,canonical_identity(v),'unsupported','Nettleseroppslag er ikke tilgjengelig i dette miljøet.')
        data=adapter.lookup(provider,v,settings=settings)
        if not isinstance(data,dict) or data.get('status') not in STATUSES:raise ValueError('Ugyldig nettlesersvar.')
        identity=canonical_identity(v)
        if data['status']=='found' and canonical_identity(data.get('identity') or {})!=identity:raise ValueError('Nettlesertreffets allel er ikke kontrollert.')
        allowed={'classification','evidence_level','accession','url','summary','details','classifications','source_version','identity_verified','identity_method','screenshot','screenshot_error'}
        return self._result(provider,identity,data['status'],str(data.get('summary','')),**{k:value for k,value in data.items() if k in allowed and k!='summary'})

    def _clinvar(self,v,tokens,settings):
        identity=canonical_identity(v)
        params={'db':'clinvar','term':f"{v['chrom']}[chr] AND {v['pos']}[chrpos37]",'retmode':'json','retmax':'100'}
        response=_json(self.transport('GET','https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',params=params))
        if not isinstance(response,dict):raise ValueError('Uventet ESearch-svar.')
        search=response.get('esearchresult')
        if not isinstance(search,dict) or not isinstance(search.get('idlist'),list):raise ValueError('Ugyldig ESearch.')
        ids=search['idlist']
        if any(not str(value).isdigit() for value in ids):raise ValueError('Ugyldig ESearch-ID.')
        count=int(search.get('count',len(ids)))
        if not ids:
            if count:raise ValueError('Avkortet ESearch.')
            return self._result('clinvar',identity,'not_found','Ingen ClinVar-post ved den oppgitte GRCh37-posisjonen.')
        raw=self.transport('GET','https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',params={'db':'clinvar','id':','.join(ids),'rettype':'vcv','is_variationid':'true','retmode':'xml'})
        root=_xml(raw);archives=[root] if root.tag=='VariationArchive' else root.findall('.//VariationArchive')
        for archive in archives:
            if archive.findtext('RecordStatus','current')!='current':continue
            record=archive.find('ClassifiedRecord');allele=record.find('SimpleAllele') if record is not None else None
            if allele is None:continue
            matched=False
            for location in allele.findall('Location/SequenceLocation'):
                a=location.attrib
                if a.get('positionVCF','').isdigit() and a.get('Assembly')=='GRCh37':
                    candidate={'assembly':'GRCh37','chrom':a.get('Chr'),'pos':int(a['positionVCF']),
                               'ref':a.get('referenceAlleleVCF','').upper(),'alt':a.get('alternateAlleleVCF','').upper()}
                    if candidate==identity:matched=True;break
            if not matched:continue
            axes={}
            for name,path in [('germline','GermlineClassification'),('somatic_clinical_impact','SomaticClinicalImpact'),('oncogenicity','OncogenicityClassification')]:
                node=record.find('Classifications/'+path)
                axes[name]=None if node is None else {'description':'; '.join(x.text.strip() for x in node.findall('Description') if x.text) or None,
                    'review_status':node.findtext('ReviewStatus') or None,'date_last_evaluated':node.get('DateLastEvaluated') or None}
            accession=archive.get('Accession','')+('.'+archive.get('Version') if archive.get('Version') else '')
            variation_id=archive.get('VariationID','');url='https://www.ncbi.nlm.nih.gov/clinvar/variation/'+variation_id+'/' if variation_id.isdigit() else HOMES['clinvar']
            labels={'germline':'Germline','somatic_clinical_impact':'Somatisk klinisk betydning','oncogenicity':'Onkogenisitet'}
            classification='; '.join(labels[k]+': '+a['description'] for k,a in axes.items() if a and a['description'])
            return self._result('clinvar',identity,'found',archive.get('VariationName','Eksakt alleltreff i ClinVar'),
                classification=classification,classifications=axes,accession=accession,url=url,
                evidence_level='; '.join(dict.fromkeys(a['review_status'] for a in axes.values() if a and a['review_status'])),
                identity_verified=True,identity_method='GRCh37 + direkte ClassifiedRecord/SimpleAllele + positionVCF/REF/ALT',
                source_version=accession,details={'source_updated':archive.get('DateLastUpdated'),'raw_sha256':hashlib.sha256(raw).hexdigest()})
        if count>len(ids):return self._result('clinvar',identity,'error','Kandidatsøket var avkortet. Fravær av eksakt alleltreff kan ikke avgjøres.')
        return self._result('clinvar',identity,'not_found','Ingen direkte ClinVar-post matchet eksakt GRCh37-posisjon, REF og ALT. Dette betyr ikke benign.')

    def _gnomad(self,v,tokens,settings):
        identity=canonical_identity(v);variant_id=f"{v['chrom']}-{v['pos']}-{v['ref']}-{v['alt']}"
        query='query Variant($variantId: String!) { variant(variantId: $variantId, dataset: gnomad_r2_1) { variant_id reference_genome rsids exome { ac an af filters } genome { ac an af filters } } }'
        payload=_json(self.transport('POST','https://gnomad.broadinstitute.org/api/',body={'query':query,'variables':{'variantId':variant_id}}))
        if not isinstance(payload,dict):raise ValueError('Uventet GraphQL-svar.')
        if payload.get('errors'):
            errors=payload['errors']
            if (isinstance(errors,list) and errors and all(isinstance(e,dict) and e.get('message')=='Variant not found' for e in errors)
                    and isinstance(payload.get('data'),dict) and payload['data'].get('variant') is None):
                return self._result('gnomad',identity,'not_found','Ingen eksakt allel i gnomAD v2.1.1. API-et svarte «Variant not found».',
                    url='https://gnomad.broadinstitute.org/variant/'+variant_id+'?dataset=gnomad_r2_1')
            raise ValueError('GraphQL-feil.')
        if not isinstance(payload.get('data'),dict) or 'variant' not in payload['data']:raise ValueError('Ugyldig GraphQL-svar.')
        record=payload['data']['variant'];url='https://gnomad.broadinstitute.org/variant/'+variant_id+'?dataset=gnomad_r2_1'
        if record is None:return self._result('gnomad',identity,'not_found','Ingen eksakt allel i gnomAD v2.1.1; dette dokumenterer ikke somatisk betydning.',url=url)
        if record.get('variant_id')!=variant_id or record.get('reference_genome')!='GRCh37':raise ValueError('gnomAD-identitet avviker.')
        summary=['gnomAD v2.1.1 (GRCh37)'];details={}
        for name,label in [('exome','Eksomer'),('genome','Genomer')]:
            row=record.get(name)
            if row is None:details[name]=None;continue
            ac=row.get('ac');an=row.get('an');af=row.get('af')
            if isinstance(ac,bool) or isinstance(an,bool) or not isinstance(ac,int) or not isinstance(an,int) or ac<0 or an<ac:raise ValueError('Ugyldige populasjonstall.')
            if af is not None and (not isinstance(af,(int,float)) or not 0<=af<=1):raise ValueError('Ugyldig frekvens.')
            details[name]={'ac':ac,'an':an,'af':af,'filters':row.get('filters',[])}
            summary.append(f'{label}: AC/AN {ac}/{an}, AF '+(format(af,'.6g') if af is not None else 'mangler'))
        return self._result('gnomad',identity,'found','; '.join(summary),accession=variant_id,url=url,
            source_version='gnomAD v2.1.1',details=details,identity_verified=True,
            identity_method='variant_id + reference_genome; exome/genome holdes atskilt')

    def _cosmic(self,v,tokens,settings):
        identity=canonical_identity(v)
        if len(v['ref'])!=1 or len(v['alt'])!=1 or not re.fullmatch(r'c\.\d+[ACGT]>[ACGT]',v.get('cdna','')):
            return self._result('cosmic',identity,'unsupported','Det offentlige COSMIC-utdraget kan bare identitetskontrolleres for en ABL1-SNV med cDNA-annotasjon. Bruk portaloppslag for flerbasealleler.')
        if not v['cdna'].endswith(v['ref']+'>'+v['alt']):
            return self._result('cosmic',identity,'unsupported','cDNA-annotasjonen avviker fra REF/ALT. Ingen COSMIC-klassifikasjon ble brukt.')
        fields=['MutationID','GeneName','MutationCDS','MutationAA','MutationGenomePosition','MutationStrand','GRChVer','AccessionNumber','PubmedPMID']
        payload=_json(self.transport('GET','https://clinicaltables.nlm.nih.gov/api/cosmic/v4/search',params={
            'terms':'ABL1 '+v['cdna'],'grchv':'37','maxList':'500','ef':','.join(fields),
            'q':'GeneName:ABL1 AND MutationCDS:"'+v['cdna']+'"'}))
        if not isinstance(payload,list) or len(payload)<3 or not isinstance(payload[1],list):raise ValueError('Ugyldig COSMIC-utdrag.')
        total=int(payload[0]);extras=payload[2] or {};ids=payload[1]
        if not isinstance(extras,dict):raise ValueError('Ugyldig COSMIC-felter.')
        matches=[];unverified=[]
        for index,code in enumerate(ids):
            row={name:values[index] if isinstance(values,list) and index<len(values) else None for name in fields for values in [extras.get(name,[])]}
            coordinate=f"{v['chrom']}:{v['pos']}-{v['pos']}"
            if str(row['GRChVer'])=='37' and row['GeneName']=='ABL1' and row['MutationGenomePosition']==coordinate and row['MutationStrand']=='+' and row['MutationCDS']==v['cdna'] and str(row['AccessionNumber']).split('.')[0]=='NM_005157':
                matches.append({k:row[k] for k in fields})
            elif (str(row['GRChVer'])=='37' and row['GeneName']=='ABL1' and row['MutationGenomePosition']==coordinate
                  and (str(row['AccessionNumber']).split('.')[0]!='NM_005157' or row['MutationStrand']!='+')):
                unverified.append({k:row[k] for k in fields})
        if matches:
            accession=', '.join(dict.fromkeys(str(r['MutationID']) for r in matches if r['MutationID']))
            return self._result('cosmic',identity,'found',f'COSMIC via NLM: {len(matches)} identitetskontrollerte SNV-poster i et begrenset offentlig utdrag. Ingen klinisk klassifikasjon.',
                accession=accession,details={'records':matches,'returned':len(ids),'total':total,'limited_public_extract':True},identity_verified=True,
                identity_method='GRCh37 + lokus + pluss-strand + NM_005157 + eksakt cDNA-SNV')
        if unverified:return self._result('cosmic',identity,'unsupported','COSMIC via NLM returnerte posisjonskandidater, men transkript/REF/ALT kunne ikke bekreftes. Ingen eksakt allelklassifikasjon ble brukt.',details={'candidate_count':len(unverified),'records':unverified,'limited_public_extract':True})
        if total>len(ids):return self._result('cosmic',identity,'error','COSMIC-utdraget var avkortet. Fravær av eksakt treff kan ikke avgjøres.')
        return self._result('cosmic',identity,'not_found','Ingen identitetskontrollert SNV i COSMICs begrensede NLM-utdrag. Full COSMIC er ikke undersøkt.')

    def _oncokb(self,v,tokens,settings):
        identity=canonical_identity(v);token=tokens.get('oncokb')
        if not token:return self._result('oncokb',identity,'license_required','OncoKB API krever organisasjonstilgang og token. Nettleserinnlogging er et eget alternativ.')
        hgvsg=genomic_hgvs(v)
        params={'hgvsg':hgvsg,'referenceGenome':'GRCh37'}
        tumor_type=settings.get('oncokb_tumor_type','')
        if tumor_type:
            if not isinstance(tumor_type,str) or len(tumor_type)>100 or any(ord(c)<32 for c in tumor_type):raise ValueError('Ugyldig sykdomskontekst.')
            params['tumorType']=tumor_type
        data=_json(self.transport('GET','https://www.oncokb.org/api/v1/annotate/mutations/byHGVSg',params=params,headers={'Authorization':'Bearer '+str(token)}))
        if not isinstance(data,dict):raise ValueError('Uventet OncoKB-svar.')
        query=data.get('query') or {}
        if query.get('hgvs')!=hgvsg or query.get('referenceGenome')!='GRCh37':raise ValueError('OncoKB-query avviker.')
        if data.get('variantExist') is not True:return self._result('oncokb',identity,'not_found','Ingen variantspesifikk OncoKB-post. Dette er ingen behandlingsklassifikasjon.')
        levels={name:data.get(name) for name in ('highestSensitiveLevel','highestResistanceLevel','highestDiagnosticImplicationLevel','highestPrognosticImplicationLevel') if data.get(name)}
        return self._result('oncokb',identity,'found',str(data.get('variantSummary') or data.get('geneSummary') or 'Variantspesifikt OncoKB-treff; vurder sykdomskontekst.'),
            classification=str(data.get('oncogenic') or ''),evidence_level='; '.join(k+': '+str(value) for k,value in levels.items()),
            accession=hgvsg,url='https://www.oncokb.org/hgvsg/'+quote(hgvsg,safe=':>')+'?refGenome=GRCh37',
            details={'mutation_effect':(data.get('mutationEffect') or {}).get('knownEffect'),'tumor_type':tumor_type or None,'levels':levels},
            source_version=str(data.get('dataVersion') or ''),identity_verified=True,identity_method='Eksakt GRCh37-HGVSg gjentatt i API-query')

    def _franklin(self,v,tokens,settings):
        identity=canonical_identity(v);token=tokens.get('franklin')
        if not token:return self._result('franklin',identity,'license_required','Franklin Premium API krever egen tilgang/token. Velg nettleseroppslag for innlogget portal.')
        query=f"chr{v['chrom']}-{v['pos']}-{v['ref']}-{v['alt']}"
        data=_json(self.transport('GET','https://api.genoox.com/v2/search/snp/',params={'search_text':query},headers={'Authorization':'Bearer '+str(token),'Accept':'application/json'}))
        def records(value):
            if isinstance(value,list):
                for item in value:yield from records(item)
            elif isinstance(value,dict):
                if isinstance(value.get('variant'),dict) and any(k in value for k in ('classification','annotations','variant_franklin_link')):yield value
                else:
                    for key in ('variants','results','data','result'):
                        if key in value:yield from records(value[key])
        candidates=list(records(data));unverified=False
        for record in candidates:
            allele=record['variant']
            build=allele.get('reference_genome') or allele.get('assembly') or record.get('reference_genome')
            if not build and isinstance(data,dict):build=data.get('reference_genome')
            if build not in ('hg19','GRCh37'):unverified=True;continue
            try:candidate=canonical_identity({'assembly':build,'chrom':allele.get('chromosome'),'pos':allele.get('start_position'),'ref':allele.get('ref'),'alt':allele.get('alt')})
            except ValueError:unverified=True;continue
            if candidate!=identity:continue
            classification=record.get('classification') or {};acmg=classification.get('acmg_classification') or classification.get('computed_classification') or ''
            url=record.get('variant_franklin_link') or HOMES['franklin']
            if urlsplit(str(url)).scheme!='https' or urlsplit(str(url)).hostname!='franklin.genoox.com':url=HOMES['franklin']
            return self._result('franklin',identity,'found','Eksakt GRCh37-allel i Franklin Premium API. Beregnet ACMG-klasse er ingen somatisk behandlingstier.',
                classification=str(acmg),accession=query,url=url,details={'classification_axis':'ACMG/germline','clinical_source':'Franklin Premium API'},
                identity_verified=True,identity_method='Eksplisitt referansebygg + chromosome/start_position/ref/alt')
        if unverified:return self._result('franklin',identity,'error','Franklin svarte, men referansebygg/allel kunne ikke bekreftes. Ingen klassifikasjon ble brukt.')
        return self._result('franklin',identity,'not_found','Ingen eksakt GRCh37-allel i Franklin API-svaret.')

    def _mtbp(self,v,tokens,settings):
        return self._result('mtbp',canonical_identity(v),'license_required','MTBP krever portaltilgang og avklart bruk. Automatisk oppretting av eksterne analyser er ikke aktivert.')
