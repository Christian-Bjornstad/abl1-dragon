"""One pseudonymous MTBP analysis per allele, with durable retry receipts.

Only exact DRAGEN-owned analyses are resumed. Existing patient reports are
never imported by gene alone, exported by URL or deleted by this adapter.
"""
from datetime import datetime,timezone
import json,os,re,tempfile,time,uuid
from pathlib import Path
from urllib.parse import urlsplit
from .lookup import canonical_identity,genomic_hgvs
from .workflow import allele_key
from .browser_evidence import evaluate

AMINO=dict(zip(('Ala Arg Asn Asp Cys Gln Glu Gly His Ile Leu Lys Met Phe Pro Ser Thr Trp Tyr Val').split(),'ARNDCQEGHILKMFPSTWYV'))
REPORT=re.compile(r'/patients/[A-Za-z0-9_-]+/report/[0-9]+/?')
class SubmissionNotSent(ValueError):pass


def short_protein(value):
    value=re.sub(r'\s+','',str(value)).removeprefix('p.')
    return re.sub(r'[A-Z][a-z]{2}',lambda m:AMINO.get(m[0],m[0]),value)


def report_url(url):
    parts=urlsplit(url)
    return (parts.scheme=='https' and parts.netloc=='mtbp.org' and not parts.query and not parts.fragment
            and bool(REPORT.fullmatch(parts.path)))


def base_result(variant,status,summary,**extra):
    return {'status':status,'summary':summary,'identity':canonical_identity(variant),'identity_verified':False,
            'classification':'','evidence_level':'','url':'',**extra}


def parse_report(variant,job,page):
    result=base_result(variant,'error','MTBP-rapporten kunne ikke knyttes entydig til varianten.')
    if (not report_url(page.get('url','')) or job['analysis_id'] not in str(page.get('text',''))
            or canonical_identity(job['identity'])!=canonical_identity(variant)):return result
    expected=short_protein(variant.get('protein_snv_alone',''));cdna=variant.get('cdna','');matches=[]
    for row in page.get('rows',[]):
        if row.get('gene')!='ABL1':continue
        identity=str(row.get('identity_text') or row.get('alteration') or '')
        returned_cdna=re.findall(r'c\.[0-9_]+(?:[ACGT]+>[ACGT]+|delins[ACGT]+|del[ACGT]*|ins[ACGT]+|dup[ACGT]*)',identity)
        if returned_cdna and (not cdna or any(c!=cdna for c in returned_cdna)):continue
        proteins=re.findall(r'(?:[A-Z][a-z]{2}|[A-Z])[0-9]+(?:[A-Z][a-z]{2}|[A-Z]|\*)',identity)
        protein_match=bool(expected and expected in {short_protein(p) for p in proteins})
        if proteins and expected and not protein_match:continue
        if protein_match or (cdna and cdna in returned_cdna):matches.append((row,'transkript/cDNA' if returned_cdna else 'protein'))
    if len(matches)!=1:return result
    row,basis=matches[0]
    classification=re.sub(r':\s*[0-9]+\s*$','',str(row.get('section',''))).strip()
    functional=' '.join(str(row.get('functional_evidence','')).split())[:1200]
    biomarkers=' '.join(str(row.get('biomarkers','')).split())[:1200]
    summary='MTBP ('+job['cancer_type']+', '+basis+'): '+classification
    if functional:summary+=' · '+functional
    if biomarkers:summary+=' · '+biomarkers
    return {**result,'status':'found','identity_verified':True,'classification':classification,'summary':summary,
            'accession':job['query'],'evidence_level':'; '.join(dict.fromkeys(re.findall(r'Evidence\s+[A-Z]',functional))),
            'identity_method':'Eget DRAGEN analyse-ID + innsendt '+job['query']+' + entydig ABL1 '+basis+' i rapporten',
            'details':{'cancer_type':job['cancer_type'],'match_basis':basis,'functional_evidence':functional,'biomarkers':biomarkers}}


def write_job(path,job):
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.mtbp-',suffix='.json',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            json.dump(job,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)


def prepare(browser,context,job):
    context.navigate('https://mtbp.org/analyse/');login_attempted=False
    for _ in range(30):
        snapshot=context.auth_snapshot() or {}
        if snapshot.get('mtbp_form') and snapshot.get('ready_state')=='complete':break
        if snapshot.get('password_visible') or snapshot.get('login_visible'):
            if login_attempted:return False
            login_attempted=True
            if not browser._saved_login('mtbp',context):return False
        time.sleep(.4)
    else:return False
    # Fixed controls used by Archer; no sample names, email or clinical files.
    for _ in range(12):
        ready=evaluate(context,'mtbp',r"""
          if(location.pathname.replace(/\/$/,'')!=='/analyse')return false;
          const id=document.querySelector('#analysis-id'),variant=document.querySelector('#variant-input'),search=document.querySelector('#cancer-search');
          if(!id||!variant||!visible(id)||!visible(variant))return false;
          const set=(e,v)=>{const type=e instanceof HTMLTextAreaElement?HTMLTextAreaElement:HTMLInputElement;Object.getOwnPropertyDescriptor(type.prototype,'value').set.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));};
          const cancer="""+json.dumps(job['cancer_type'])+""";
          const choices=[...document.querySelectorAll('[role=treeitem]')].filter(e=>visible(e)&&(e.getAttribute('aria-label')||e.innerText).trim()===cancer);
          if(choices.length!==1){if(search)set(search,cancer);return false;}
          if(choices[0].getAttribute('aria-selected')!=='true')choices[0].click();
          set(id,"""+json.dumps(job['analysis_id'])+""");set(variant,"""+json.dumps(job['query'])+""");return true;""")
        if ready:return True
        time.sleep(.3)
    return False


def submit(context,job):
    accepted=evaluate(context,'mtbp',r"""
      if(location.pathname.replace(/\/$/,'')!=='/analyse')return false;
      const ids=[...document.querySelectorAll('#analysis-id')],variants=[...document.querySelectorAll('#variant-input')],buttons=[...document.querySelectorAll('#run-analysis')];
      if(ids.length!==1||variants.length!==1||buttons.length!==1)return false;
      const button=buttons[0];if(!visible(button)||button.disabled)return false;
      if(ids[0].value!=="""+json.dumps(job['analysis_id'])+"""||variants[0].value!=="""+json.dumps(job['query'])+""")return false;
      if([...document.querySelectorAll('input[type=checkbox][required]:not(:checked),iframe[src*="/recaptcha/"][src*="/bframe"]')].some(visible))return false;
      if(button.form){const url=new URL(button.formAction||button.form.action||location.href,location.href);if(url.origin!==location.origin)return false;}
      button.click();return true;""")
    if not accepted:raise SubmissionNotSent('MTBP-skjemaet kunne ikke sendes automatisk. Kontroller vinduet i Edge.')


def wait_acceptance(context,job):
    # Do not navigate away from an in-flight native POST or AJAX submission.
    for _ in range(40):
        state=evaluate(context,'mtbp',r"""
          const input=document.querySelector('#variant-input'),id=document.querySelector('#analysis-id');
          return {url:location.href,ready:document.readyState,query:input?.value||'',id:id?.value||'',
                  text:location.pathname.replace(/\/$/,'')==='/analyse'?(document.body?.innerText||'').slice(0,20000):''};""") or {}
        parts=urlsplit(state.get('url',''))
        if parts.scheme=='https' and parts.netloc=='mtbp.org':
            if re.fullmatch(r'/queue/[0-9]+/?',parts.path) or report_url(state['url']):return 'accepted'
            if (state.get('ready')=='complete' and state.get('id')==job['analysis_id'] and state.get('query')==job['query']
                    and job['query'] in state.get('text','') and 'cannot be mapped to genomic coordinates' in state.get('text','')):return 'rejected'
        time.sleep(.5)
    return 'unknown'


def read_report(context):
    return evaluate(context,'mtbp',r"""
      if(!/^\/patients\/[A-Za-z0-9_-]+\/report\/[0-9]+\/?$/.test(location.pathname))return null;
      const rows=[...document.querySelectorAll('table')].filter(visible).flatMap(table=>{
        const rows=[...table.rows];if(!rows.length)return [];
        const headers=[...rows[0].cells].map(c=>c.innerText.trim());
        if(headers[0]!=='Gene'||headers[2]!=='Alteration'||!headers[4]?.startsWith('Reported biomarker'))return [];
        const section=table.closest('.accordion-item')?.firstElementChild?.innerText?.trim()||'';
        return rows.slice(1).filter(visible).map(row=>{const cells=[...row.cells];return {
          gene:((cells[0]?.innerText||'').trim().match(/[A-Za-z0-9-]+/)||[''])[0],
          alteration:cells[2]?.innerText.trim()||'',identity_text:cells[2]?.textContent.trim()||'',
          section,functional_evidence:cells[3]?.innerText.trim()||'',biomarkers:cells[4]?.innerText.trim()||''};});
      });return {url:location.href,text:(document.body?.innerText||'').slice(0,120000),rows,ready_state:document.readyState};""")


def find_report(context,job):
    page=read_report(context)
    if page and job['analysis_id'] in page['text'] and page['ready_state']=='complete' and page['rows']:return page
    # Query only the exact random ID. Never copy the account's report list or
    # another patient's name into a receipt, screenshot or Excel workbook.
    current=context.auth_snapshot() or {}
    if urlsplit(current.get('url','')).path.rstrip('/')!='/patients':context.navigate('https://mtbp.org/patients/')
    target=evaluate(context,'mtbp',r"""
      if(location.pathname.replace(/\/$/,'')!=='/patients'||document.readyState!=='complete')return null;
      const id="""+json.dumps(job['analysis_id'])+""";
      const links=[...document.querySelectorAll('a[href]')].filter(e=>visible(e)&&e.innerText.trim()===id);
      return links.length===1?links[0].href:null;""")
    if target and report_url(target):context.navigate(target)
    return None


def capture(context,variant,job,page,result,root):
    path=None
    try:
        # A single-variant, app-owned report may have one gene in several
        # functional sections. Parse identity first; capture only one match.
        before=read_report(context)
        if not before or parse_report(variant,job,before)['status']!='found':raise ValueError('MTBP-resultatet ble endret.')
        context._page_call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
        time.sleep(.3)
        clip=evaluate(context,'mtbp',"""
          const protein="""+json.dumps(short_protein(variant.get('protein_snv_alone','')))+""";
          const cdna="""+json.dumps(str(variant.get('cdna') or ''))+""";
          const amino="""+json.dumps(AMINO)+""";
          const candidates=[...document.querySelectorAll('table tr')].filter(visible).filter(row=>{
            const cells=[...row.cells];if(cells.length<5||!/^ABL1\\b/.test(cells[0].innerText.trim()))return false;
            const text=(cells[2].textContent||'').replace(/[A-Z][a-z]{2}/g,a=>amino[a]||a);return (cdna&&text.includes(cdna))||(protein&&text.includes(protein));
          });if(candidates.length!==1)return null;
          const row=candidates[0];row.scrollIntoView({block:'center'});
          const table=row.closest('table'),r=row.getBoundingClientRect(),header=table.rows[0].getBoundingClientRect();
          const x=Math.max(0,Math.min(r.left,header.left)-12)+scrollX,y=Math.max(0,Math.min(r.top,header.top)-24)+scrollY;
          return {x,y,width:Math.max(r.right,header.right)+scrollX-x+12,height:Math.max(100,r.bottom+scrollY-y+24)};""")
        if not clip:raise ValueError('MTBP-variantens bildefelt finnes ikke.')
        root.mkdir(parents=True,exist_ok=True);path=root/('mtbp-'+uuid.uuid4().hex+'.png')
        context.capture_png(path,clip=clip)
        after=read_report(context)
        if not after or after['url']!=before['url'] or after['rows']!=before['rows'] or parse_report(variant,job,after)['status']!='found':raise ValueError('MTBP-resultatet ble endret under bildeuttak.')
        captured=datetime.now(timezone.utc).isoformat()
        return {**result,'screenshot':str(path),'captured_at':captured,'screenshots':[
            {'path':str(path),'label':'MTBP · '+job['cancer_type']+' · alteration-centric evidence','url':'','captured_at':captured}]}
    except (OSError,ValueError,RuntimeError,TimeoutError):
        if path:path.unlink(missing_ok=True)
        return {**result,'screenshot_error':'MTBP-bildet kunne ikke hentes. Søk igjen for å åpne samme analyse.','screenshot_reason':'capture_failed'}


def lookup_mtbp(browser,variant,settings):
    root=browser.data_dir/'evidence/databases'/allele_key(variant);path=root/'mtbp-job.json'
    context=browser._context('mtbp');job=None
    query='NM_005157.6:'+variant['cdna'] if variant.get('cdna') else 'chr'+genomic_hgvs(variant)
    if path.exists():
        if path.stat().st_size>16384:raise ValueError('Ugyldig MTBP-kvittering.')
        job=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(job,dict):raise ValueError('Ugyldig MTBP-kvittering.')
        if (not isinstance(job.get('analysis_id'),str) or not re.fullmatch(r'DRAGEN-[0-9a-f]{32}',job['analysis_id'])
                or canonical_identity(job.get('identity') or {})!=canonical_identity(variant)
                or job.get('query') not in {query,'chr'+genomic_hgvs(variant)} or job.get('cancer_type')!='Blood'):raise ValueError('Ugyldig MTBP-variant.')
    def pending():
        return base_result(variant,'pending','MTBP-analysen er ikke ferdig eller innlogging må fullføres. Søk igjen for å hente samme analyse.',
                           accession=job['query'],details={'analysis_id':job['analysis_id'],'cancer_type':job['cancer_type']})
    if job is None:
        cancer_type=str(settings.get('mtbp_cancer_type') or 'Blood')
        if cancer_type!='Blood':return base_result(variant,'unsupported','Denne MTBP-flyten bruker sykdomskategorien Blood.')
        job={'analysis_id':'DRAGEN-'+uuid.uuid4().hex,'identity':canonical_identity(variant),'query':query,
             'cancer_type':cancer_type,'created_at':datetime.now(timezone.utc).isoformat()}
        for attempt in range(2):
            if not prepare(browser,context,job):return base_result(variant,'login_required','Åpne MTBP under Innstillinger og fullfør innlogging/skjemaet i Edge.')
            # Commit intent before clicking. An uncertain response must never
            # cause a second submission, even after a process crash/restart.
            write_job(path,job)
            try:
                submit(context,job);acceptance=wait_acceptance(context,job)
            except SubmissionNotSent as error:
                path.unlink(missing_ok=True);return base_result(variant,'error',str(error))
            except (OSError,RuntimeError,TimeoutError):return pending()
            if acceptance=='accepted':break
            if acceptance=='rejected':
                # Only a positively rejected, exact form may be retried with
                # genomic HGVS. Never resubmit after an uncertain response.
                if attempt==0 and job['query']!='chr'+genomic_hgvs(variant):
                    job['query']='chr'+genomic_hgvs(variant);continue
                path.unlink(missing_ok=True)
                return base_result(variant,'error','MTBP kunne ikke kartlegge varianten med transkript eller GRCh37-HGVS.')
            return pending()
    timeout=min(120,max(0,float(settings.get('mtbp_wait_seconds',20))))
    deadline=time.monotonic()+timeout
    while True:
        page=find_report(context,job)
        if page is not None:
            result=parse_report(variant,job,page)
            if result['status']=='found':
                result=capture(context,variant,job,page,result,root)
                from .evidence_store import EvidenceStore
                EvidenceStore(browser.data_dir).save(variant,{'provider':'mtbp','checked_at':datetime.now(timezone.utc).isoformat(),**result})
            return result
        if time.monotonic()>=deadline:break
        time.sleep(2)
    return pending()
