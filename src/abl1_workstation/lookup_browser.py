"""Selected-variant portal retrieval through app-owned, logged-in Edge profiles.

Uses an ephemeral loopback DevTools endpoint in an app-owned Edge profile.
Credentials are entered in Edge. No cookies/passwords are read by this module.
Portal text is untrusted data; identity and meaningful result markers are checked.
"""
from __future__ import annotations
import atexit
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote, unquote, urlsplit, parse_qs
from urllib.request import ProxyHandler, build_opener

from .database_browser import EdgeBrowser, checked_url
from .lookup import canonical_identity, genomic_hgvs, _NoRedirect

LOGIN_URLS={'franklin':'https://franklin.genoox.com/login',
            'oncokb':'https://www.oncokb.org/login',
            'cosmic':'https://cancer.sanger.ac.uk/cosmic/login',
            'mtbp':'https://mtbp.org/analyse/'}
PORTAL_HOSTS={'franklin':{'franklin.genoox.com'},'oncokb':{'www.oncokb.org'},
              'cosmic':{'cancer.sanger.ac.uk','grch37-cancer.sanger.ac.uk'},'mtbp':{'mtbp.org'}}
CLASS_LABELS=r'(?<![A-Za-z])(?:Likely pathogenic|Pathogenic|Likely benign|Benign|Uncertain significance|VUS|Likely oncogenic|Oncogenic|Likely neutral|Neutral|Inconclusive)(?![A-Za-z])'


def login_status(provider,snapshot):
    """An open window or a saved profile does not prove a current login."""
    result={'status':'unknown','summary':'Innlogging ikke bekreftet','checked_at':datetime.now(timezone.utc).isoformat()}
    parts=urlsplit(str(snapshot.get('url','')))
    if parts.scheme!='https' or parts.hostname not in PORTAL_HOSTS.get(provider,set()):return result
    if snapshot.get('password_visible') or re.search(r'/(?:login|sign-?in|auth)(?:/|$)',parts.path,re.I):
        return {**result,'status':'logged_out','summary':'Ikke innlogget'}
    if snapshot.get('logout_visible'):
        return {**result,'status':'logged_in','summary':'Innlogget'}
    if provider=='franklin' and parts.path.startswith('/clinical-db/') and snapshot.get('franklin_search'):
        return {**result,'status':'logged_in','summary':'Innlogget'}
    if provider=='mtbp' and parts.path.rstrip('/')=='/analyse' and snapshot.get('mtbp_form'):
        return {**result,'status':'logged_in','summary':'Innlogget'}
    if snapshot.get('login_visible'):
        return {**result,'status':'logged_out','summary':'Ikke innlogget'}
    return result


def _labelled_classifications(provider,text):
    """Only a concrete classification label followed by one unambiguous value.

    Do not scrape every class term in legends, tool menus or general help text.
    A changed site layout must produce an explicit retrieval error, not a guess.
    """
    labels=(r'Suggested classification|Computed classification|ACMG classification|Oncogenic classification|Oncogenicity'
            if provider=='franklin' else r'Oncogenicity|Oncogenic classification|Biological effect')
    lines=[' '.join(line.split()) for line in text.splitlines() if line.strip()]
    found=[]
    for i,line in enumerate(lines):
        heading=re.fullmatch('('+labels+r')(?:\s*[:\-]\s*(.*))?',line,re.I)
        if not heading:continue
        value=(heading[2] or (lines[i+1] if i+1<len(lines) else '')).strip()
        if not re.fullmatch(CLASS_LABELS,value,re.I):continue
        # Adjacent class values usually form a legend/menu, not a result badge.
        next_index=i+1 if heading[2] else i+2
        if next_index<len(lines) and re.fullmatch(CLASS_LABELS,lines[next_index],re.I):continue
        pair=(heading[1],value)
        if pair not in found:found.append(pair)
    return found


def _labelled_levels(text):
    labels=r'Evidence level|Resistance level|Sensitivity level|Diagnostic level|Prognostic level'
    value_pattern=r'(?:LEVEL_)?(?:R[12]|[1-4][A-D]?|A[12]|Dx[1-3]|Px[1-3])'
    lines=[' '.join(line.split()) for line in text.splitlines() if line.strip()]
    found=[]
    for i,line in enumerate(lines):
        heading=re.fullmatch('('+labels+r')(?:\s*[:\-]\s*(.*))?',line,re.I)
        if not heading:continue
        value=(heading[2] or (lines[i+1] if i+1<len(lines) else '')).strip()
        if not re.fullmatch(value_pattern,value,re.I):continue
        next_index=i+1 if heading[2] else i+2
        if next_index<len(lines) and re.fullmatch(value_pattern,lines[next_index],re.I):continue
        pair=(heading[1],value)
        if pair not in found:found.append(pair)
    return found


def _portal_url(url):
    # COSMIC's official GRCh37 host is used by mutation-result redirects.
    if isinstance(url,str) and url.startswith('https://grch37-cancer.sanger.ac.uk/'):
        checked_url('https://cancer.sanger.ac.uk/'+url.split('https://grch37-cancer.sanger.ac.uk/',1)[1])
        return url
    return checked_url(url)


def debugging_policy():
    """Do not bypass an organisation policy prohibiting browser instrumentation."""
    if sys.platform!='win32':return 'Kontrollert portaloppslag krever Windows/Edge.'
    import winreg
    try:
        for root in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(root,r'Software\Policies\Microsoft\Edge',0,winreg.KEY_READ|view) as key:
                        for name in ('RemoteDebuggingAllowed','DeveloperToolsAvailability'):
                            try:value,_=winreg.QueryValueEx(key,name)
                            except FileNotFoundError:continue
                            if (name=='RemoteDebuggingAllowed' and value==0) or (name=='DeveloperToolsAvailability' and value==2):
                                return 'Edge-policy blokkerer kontrollert portaloppslag. Avklar med IT.'
                except FileNotFoundError:continue
    except OSError:return 'Edge-policy kunne ikke kontrolleres. Avklar med IT.'
    return None


def parse_portal_snapshot(provider,variant,snapshot):
    identity=canonical_identity(variant)
    result={'status':'error','summary':'Portalen viser ikke et ferdig, identitetskontrollert variantresultat.',
            'classification':'','evidence_level':'','accession':'','url':str(snapshot.get('url','')),
            'identity':identity,'identity_verified':False}
    url=result['url'];parts=urlsplit(url);text=str(snapshot.get('text',''))[:120_000]
    if parts.scheme!='https' or parts.hostname not in PORTAL_HOSTS.get(provider,set()):
        result['summary']='Portalen navigerte utenfor den forventede databaseverten.';return result
    if snapshot.get('password_visible') or re.search(r'/(?:login|sign-?in|auth)(?:/|$)',parts.path,re.I):
        return {**result,'status':'login_required','summary':'Logg inn i denne kildens Edge-vindu under Innstillinger, og kjør oppslaget igjen.'}
    if re.search(r'subscription (?:has )?expired|quota.{0,20}(?:exceeded|exhausted)|upgrade.{0,30}(?:plan|subscription)|license required',text,re.I):
        return {**result,'status':'license_required','summary':'Kildens kvote/lisens gir ikke tilgang til dette resultatet.'}
    if re.search(r'access denied|captcha|verify you are human|checking your browser',text,re.I):
        result['summary']='Nettstedet blokkerer eller krever manuell kontroll i Edge.';return result
    compact=re.sub(r'\s+','',unquote(text));route=unquote(url)
    build37=bool(re.search(r'(?<!\w)(?:GRCh37|hg19)(?!\w)',text,re.I))
    build38=bool(re.search(r'(?<!\w)(?:GRCh38|hg38)(?!\w)',text,re.I))
    identity_method=''
    if provider=='franklin':
        needle=f"chr{identity['chrom']}-{identity['pos']}-{identity['ref']}-{identity['alt']}"
        route_match=re.search(r'/variant/snp/([^/?#]+)',route)
        exact=route_match is not None and route_match[1]==needle and needle in compact and build37 and not build38
        ready=bool(re.search(r'Suggested classification|Computed classification|ACMG classification|Oncogenic classification|Oncogenicity',text,re.I))
        identity_method='Franklin GRCh37/hg19 + eksakt variant-rute + synlig VCF-allel'
    elif provider=='oncokb':
        hgvs=genomic_hgvs(variant);route_match=re.search(r'/hgvsg/([^?#]+)',route)
        ref=parse_qs(parts.query).get('refGenome',[])
        exact=route_match is not None and route_match[1]==hgvs and ref==['GRCh37'] and hgvs in compact and not build38
        ready=bool(re.search(r'Oncogenic|Likely oncogenic|Resistance|Mutation effect|Biological effect',text,re.I))
        identity_method='OncoKB eksakt HGVSg-rute + refGenome=GRCh37 + synlig genomisk allel'
    elif provider=='cosmic':
        coordinate=f"{identity['chrom']}:{identity['pos']}-{identity['pos']+len(identity['ref'])-1}"
        cdna=variant.get('cdna','');protein=variant.get('protein_snv_alone','')
        exact=(len(identity['ref'])==len(identity['alt'])==1 and build37 and not build38
               and coordinate in compact and cdna and cdna in compact and 'NM_005157' in text and re.search(r'\bABL1\b',text))
        ready='Overview' in text and ('Tissue distribution' in text or 'Samples' in text)
        identity_method='COSMIC GRCh37 + synlig NM_005157/cDNA-SNV + genomisk lokus'
    else:return {**result,'status':'unsupported','summary':'Ingen kontrollert portaluttrekker for denne kilden.'}
    if not exact:
        result['summary']='Portalen kunne ikke bekrefte eksakt referansebygg, posisjon og allel. Ingen klassifikasjon ble brukt.';return result
    if re.search(r'variant not found|no variants? found|no matching variant',text,re.I):
        return {**result,'status':'not_found','summary':'Portalen rapporterte ingen variant for det identitetskontrollerte søket. Dette betyr ikke benign.'}
    if not ready:return result
    classifications=_labelled_classifications(provider,text)
    if provider!='cosmic' and not classifications:return result
    levels=_labelled_levels(text)
    excerpt=[label+': '+value for label,value in classifications+levels]
    classification='; '.join(label+': '+value for label,value in classifications) if provider=='franklin' else '; '.join(value for _,value in classifications)
    return {**result,'status':'found','classification':classification,'evidence_level':'; '.join(label+': '+value for label,value in levels),
            'summary':f'{provider.title()}: identitetskontrollert portalresultat. '+(' | '.join(excerpt[:8]) if excerpt else 'COSMIC oversikt og kildeinnhold er tilgjengelig.'),
            'identity_verified':True,'identity_method':identity_method,
            'accession':genomic_hgvs(variant),'classifications':{label:{'description':value} for label,value in classifications},
            'details':{'portal_excerpt':excerpt[:12],'retrieval':'visible authenticated portal content'}}


class _WebSocketConnection:
    """CDP connection restricted to the endpoint announced by our own profile."""
    def __init__(self,url,expected_port):
        parts=urlsplit(url)
        if (parts.scheme!='ws' or parts.hostname!='127.0.0.1' or parts.port!=expected_port
                or parts.username is not None or parts.password is not None or parts.query or parts.fragment
                or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{16,80}',parts.path)):
            raise ValueError('Edge annonserte en uventet lokal kontrolladresse.')
        import socket
        import websocket
        self._timeout_error=websocket.WebSocketTimeoutException
        self._connection_error=websocket.WebSocketException
        self._socket=None;self._counter=0;self._lock=threading.Lock()
        transport=socket.create_connection(('127.0.0.1',expected_port),timeout=10)
        try:
            # Explicit loopback socket avoids routing CDP through an environment
            # proxy. No wildcard Origin or external debugging address is used.
            self._socket=websocket.create_connection(url,socket=transport,timeout=20,suppress_origin=True,
                                                    enable_multithread=True)
        except BaseException:transport.close();raise
    def call(self,method,params=None,*,session_id=None,timeout=20):
        with self._lock:
            if self._socket is None:raise RuntimeError('Edge-forbindelsen er lukket.')
            self._counter+=1;identifier=self._counter
            message={'id':identifier,'method':method,'params':params or {}}
            if session_id:message['sessionId']=session_id
            self._socket.send(json.dumps(message,separators=(',',':')))
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                self._socket.settimeout(max(.01,deadline-time.monotonic()))
                try:raw=self._socket.recv()
                except (TimeoutError,self._timeout_error):raise TimeoutError('Edge svarte ikke innen tidsgrensen.') from None
                except self._connection_error:raise RuntimeError('Edge-vinduet eller forbindelsen ble lukket.') from None
                if not raw:raise RuntimeError('Edge-vinduet eller forbindelsen ble lukket.')
                if len(raw)>8*1024*1024:raise RuntimeError('Edge-svaret er for stort.')
                response=json.loads(raw)
                if response.get('id')!=identifier:continue
                if 'error' in response:raise RuntimeError('Edge avviste portalforespørselen.')
                return response.get('result',{})
            raise TimeoutError('Edge svarte ikke innen tidsgrensen.')
    def close(self):
        if self._socket is not None:
            try:self._socket.close()
            except (OSError,self._connection_error):pass
            finally:self._socket=None


def _owned_endpoint(profile,port_file,started):
    """Read only a newly created marker under this launch's leased profile."""
    if port_file.resolve().parent!=profile or port_file.stat().st_mtime_ns<started:
        raise ValueError('Edge-kontrollmarkøren tilhører ikke denne oppstarten.')
    if port_file.stat().st_size>256:raise ValueError('Ugyldig Edge-kontrollmarkør.')
    lines=port_file.read_text(encoding='utf-8').splitlines()
    if len(lines)!=2 or not lines[0].isdigit() or not 1024<=int(lines[0])<=65535:
        raise ValueError('Ugyldig lokal Edge-port.')
    path=lines[1]
    if not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{16,80}',path):raise ValueError('Ugyldig Edge-kontrollsti.')
    port=int(lines[0]);endpoint=f'http://127.0.0.1:{port}'
    with build_opener(ProxyHandler({}),_NoRedirect()).open(endpoint+'/json/version',timeout=1) as response:
        raw=response.read(65537)
        if len(raw)>65536:raise ValueError('Ugyldig Edge-versjonssvar.')
    version=json.loads(raw)
    url=version.get('webSocketDebuggerUrl','')
    if url!=f'ws://127.0.0.1:{port}{path}':raise ValueError('Edge-versjonssvaret avviker fra oppstartsmarkøren.')
    if 'Edg/' not in str(version.get('Browser','')):raise ValueError('Kontrollendepunktet er ikke Microsoft Edge.')
    return url,port


def _initial_target(connection):
    targets=connection.call('Target.getTargets').get('targetInfos',[])
    pages=[row for row in targets if isinstance(row,dict) and row.get('type')=='page' and row.get('targetId')]
    # Launch already requests an about:blank tab. Reuse it instead of leaving
    # one empty tab next to every provider login/search page.
    page=next((row for row in pages if row.get('url')=='about:blank'),None)
    if page:return page['targetId']
    if pages:return pages[0]['targetId']
    return connection.call('Target.createTarget',{'url':'about:blank'})['targetId']


class _EdgeContext:
    def __init__(self,executable,profile):
        if sys.platform!='win32':raise RuntimeError('Portaloppslag krever Windows/Edge.')
        self.profile=Path(profile);self.profile.mkdir(parents=True,exist_ok=True)
        if self.profile.resolve()!=self.profile:raise RuntimeError('Edge-profilen peker til en annen mappe.')
        self._lease_path=self.profile/'.abl1-portal.lock';self._lease=None;self._process=None;self._connection=None;self._startup_stderr=None
        try:self._lease=os.open(self._lease_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise RuntimeError('Portalprofilen er i bruk eller ble ikke avsluttet. Lukk appens portalvindu før nytt forsøk.') from None
        os.write(self._lease,str(os.getpid()).encode())
        try:
            self._startup_stderr=tempfile.TemporaryFile(mode='w+b')
            port_file=self.profile/'DevToolsActivePort'
            # The exclusive app lease excludes another app launch. Never attach
            # to an existing marker/browser left by an earlier process.
            if port_file.exists():raise RuntimeError('En tidligere Edge-kontrollmarkør finnes. Lukk appens portalvindu og avklar profilen før nytt forsøk.')
            self._port_file=port_file;started=time.time_ns()
            args=[str(executable),'--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
                  '--user-data-dir='+str(self.profile),'--profile-directory=Default','--no-first-run',
                  '--no-default-browser-check','--disable-background-mode','--disable-features=msEdgeStartupBoost',
                  '--new-window','about:blank']
            self._process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=self._startup_stderr,
                                           close_fds=True,shell=False)
            deadline=time.monotonic()+25;last_error=None
            while time.monotonic()<deadline:
                if self._process.poll() not in (None,0):raise RuntimeError('Edge-prosessen kunne ikke starte.')
                try:
                    url,port=_owned_endpoint(self.profile,port_file,started)
                    self._connection=_WebSocketConnection(url,port)
                    break
                except (OSError,ValueError,RuntimeError) as error:last_error=error
                time.sleep(.2)
            if self._connection is None:raise RuntimeError('Edge annonserte ingen gyldig lokal kontrollforbindelse.') from last_error
            self._connection.call('Browser.getVersion',timeout=25)
            target=_initial_target(self._connection)
            self._target=target
            self._session=self._connection.call('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
            self._connection.call('Page.enable',session_id=self._session)
        except BaseException as error:
            code=self._process.poll() if self._process else None
            stderr=''
            if self._startup_stderr is not None:
                self._startup_stderr.flush();self._startup_stderr.seek(0)
                stderr=self._startup_stderr.read(16384).decode('utf-8','replace')
            # Startup only: no page/login navigation has occurred at this point.
            # Keep developer evidence outside source and never include DOM data.
            diagnostic=self.profile.parents[1]/'work/launcher-logs/edge-startup.log'
            try:
                diagnostic.parent.mkdir(parents=True,exist_ok=True)
                diagnostic.write_text('Edge startup exit='+str(code)+'\n'+stderr,encoding='utf-8')
            except OSError:diagnostic=None
            self.close()
            raise RuntimeError('Edge startet ikke kontrollert portalforbindelse. Avslutningskode: '+str(code)+
                               ('. Oppstartslogg: '+str(diagnostic) if diagnostic else '')+'.') from error
    def evaluate(self,expression):
        result=self._connection.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True,'userGesture':True},session_id=self._session)
        if result.get('exceptionDetails'):raise RuntimeError('Nettstedets oppslag kunne ikke utføres.')
        return (result.get('result') or {}).get('value')
    def navigate(self,url):
        _portal_url(url)
        self._connection.call('Page.navigate',{'url':url},session_id=self._session)
    def snapshot(self):
        return self.evaluate("""(()=>{
          const visible=x=>x.getClientRects().length>0;
          const controls=Array.from(document.querySelectorAll('a,button,[role=button],[role=menuitem]')).filter(visible);
          const caption=x=>(x.innerText||x.getAttribute('aria-label')||'').trim();
          return {url:location.href,text:(document.body?document.body.innerText:'').slice(0,120000),
            password_visible:Array.from(document.querySelectorAll('input[type=password]')).some(visible),
            franklin_search:Array.from(document.querySelectorAll("input[placeholder='Enter variant, gene or select an example above']")).some(visible),
            mtbp_form:Array.from(document.querySelectorAll('#variant-input')).some(visible),
            logout_visible:controls.some(x=>/^(?:log\\s*out|sign\\s*out|logout)$/i.test(caption(x))),
            login_visible:controls.some(x=>/^(?:log\\s*in|sign\\s*in|login)$/i.test(caption(x)))};
        })()""")

    def is_alive(self):
        if self._connection is None:return False
        try:
            targets=self._connection.call('Target.getTargets',timeout=3).get('targetInfos',[])
            return any(t.get('targetId')==self._target and t.get('type')=='page' for t in targets)
        except (OSError,RuntimeError,TimeoutError,ValueError):return False

    def bring_to_front(self):
        self._connection.call('Page.bringToFront',session_id=self._session,timeout=3)
    def close(self):
        if self._connection:
            try:self._connection.call('Browser.close',timeout=3)
            except (OSError,RuntimeError,TimeoutError):pass
            self._connection.close();self._connection=None
        if self._process:
            try:self._process.wait(timeout=4)
            except subprocess.TimeoutExpired:self._process.terminate()
            self._process=None
        port_file=getattr(self,'_port_file',None)
        if port_file is not None and self._connection is None:
            # Our owned browser has been asked to exit before removing its
            # bootstrap marker. No ordinary Edge profile/process is touched.
            try:port_file.unlink(missing_ok=True)
            except OSError:pass
        if self._lease is not None:
            os.close(self._lease);self._lease=None
            try:self._lease_path.unlink(missing_ok=True)
            except OSError:pass
        if self._startup_stderr is not None:
            self._startup_stderr.close();self._startup_stderr=None


class PortalBrowser:
    def __init__(self,data_dir,edge_browser=None,*,context_factory=None):
        self.data_dir=Path(data_dir).resolve();self.edge=edge_browser or EdgeBrowser(self.data_dir)
        self.profile_dir=self.data_dir/'PortalProfiler'
        self._context_factory=context_factory or _EdgeContext
        self._contexts={};self._locks={p:threading.RLock() for p in LOGIN_URLS};self._closed=False
        atexit.register(self.close)
    def diagnostics(self):
        result=dict(self.edge.diagnostics());result['profile_dir']=str(self.profile_dir)
        result['authenticated']=None;result['controlled_portal_profiles']=list(self._contexts)
        result['portal_policy_warning']=debugging_policy()
        return result
    def executable_path(self):return self.edge.executable_path()
    def set_executable(self,path):return self.edge.set_executable(path)
    def _context(self,provider):
        if self._closed:raise RuntimeError('Portalvisningen er lukket.')
        warning=self.edge.diagnostics().get('warning') or debugging_policy()
        if warning:raise RuntimeError(warning)
        executable=self.edge.executable_path()
        if executable is None:raise RuntimeError('Microsoft Edge ble ikke funnet.')
        existing=self._contexts.get(provider)
        if existing is not None and hasattr(existing,'is_alive') and not existing.is_alive():self._discard(provider)
        if provider not in self._contexts:self._contexts[provider]=self._context_factory(executable,self.profile_dir/provider)
        return self._contexts[provider]

    def _discard(self,provider):
        existing=self._contexts.pop(provider,None)
        if existing:
            try:existing.close()
            except (OSError,RuntimeError,TimeoutError):pass

    def status(self,provider):
        if provider not in self._locks:return {'status':'public','summary':'Åpen kilde'}
        with self._locks[provider]:
            context=self._contexts.get(provider)
            if context is None:return {'status':'closed','summary':'Vindu lukket'}
            try:
                if hasattr(context,'is_alive') and not context.is_alive():
                    self._discard(provider);return {'status':'closed','summary':'Vindu lukket'}
                return login_status(provider,context.snapshot() or {})
            except (OSError,RuntimeError,TimeoutError,ValueError):return {'status':'unknown','summary':'Innlogging ikke bekreftet'}

    def open_login(self,provider):
        if provider not in LOGIN_URLS:raise ValueError('Kilden har ingen portalinnlogging.')
        with self._locks[provider]:
            context=self._context(provider)
            if self.status(provider).get('status')!='logged_in':context.navigate(LOGIN_URLS[provider])
            if hasattr(context,'bring_to_front'):context.bring_to_front()
    def open_url(self,url):
        checked_url(url);host=urlsplit(url).hostname
        provider=next((p for p,hosts in PORTAL_HOSTS.items() if host in hosts),None)
        if provider:
            with self._locks[provider]:return self._context(provider).navigate(url)
        return self.edge.open_url(url)
    def lookup(self,provider,variant,*,settings=None):
        if provider=='mtbp':return {'status':'unsupported','summary':'MTBP-oppslag oppretter eksterne analyser. Denne adapteren sender eller sletter ingen slike rapporter.'}
        if provider not in ('franklin','oncokb','cosmic'):return {'status':'unsupported','summary':'Kilden bruker offentlig API-adapter.'}
        settings=settings or {}
        with self._locks[provider]:
            context=self._context(provider)
            if provider=='franklin':
                v=canonical_identity(variant)
                url=f"https://franklin.genoox.com/clinical-db/variant/snp/chr{v['chrom']}-{v['pos']}-{v['ref']}-{v['alt']}"
            elif provider=='oncokb':url='https://www.oncokb.org/hgvsg/'+quote(genomic_hgvs(variant),safe=':>')+'?refGenome=GRCh37'
            else:url='https://cancer.sanger.ac.uk/cosmic/search?q='+quote('ABL1 '+str(variant.get('cdna','')))
            context.navigate(url)
            timeout=min(max(float(settings.get('browser_timeout_seconds',30)),5),90)
            deadline=time.monotonic()+timeout;result=None
            while time.monotonic()<deadline:
                snapshot=context.snapshot() or {};result=parse_portal_snapshot(provider,variant,snapshot)
                if result['status'] in {'found','not_found','login_required','license_required'}:return result
                if provider=='cosmic' and hasattr(context,'evaluate'):
                    # Only follow a specific mutation-result link, never a login,
                    # download, report creation, acceptance, or account action.
                    target=context.evaluate("Array.from(document.querySelectorAll('a[href]')).map(a=>a.href).find(x=>/^https:\\/\\/(?:grch37-)?cancer\\.sanger\\.ac\\.uk\\/cosmic\\/(?:mutation\\/overview|mutation\\/.*overview)/.test(x))||null")
                    if target and target!=snapshot.get('url') and urlsplit(target).hostname in PORTAL_HOSTS['cosmic']:
                        context.navigate(target)
                time.sleep(.75)
            return result or {'status':'error','summary':'Portalresultatet ble ikke ferdig innen tidsgrensen.'}
    def close(self):
        if self._closed:return
        self._closed=True
        for provider,context in list(self._contexts.items()):
            with self._locks[provider]:
                try:context.close()
                except (OSError,RuntimeError,TimeoutError):pass
        self._contexts.clear()
    shutdown=close
