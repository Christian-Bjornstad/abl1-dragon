"""Selected-variant portal retrieval through app-owned, logged-in Edge profiles.

Uses an ephemeral loopback DevTools endpoint in an app-owned Edge profile.
Saved accounts are filled only into allowlisted same-origin login forms.
Portal text is untrusted data; identity and meaningful result markers are checked.
"""
from __future__ import annotations
import atexit
import base64
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
import uuid
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
PUBLIC_HOSTS={'clinvar':{'www.ncbi.nlm.nih.gov'},'gnomad':{'gnomad.broadinstitute.org'}}
PORTAL_HOSTS.update(PUBLIC_HOSTS)
CLASS_LABELS=r'(?<![A-Za-z])(?:Likely pathogenic|Pathogenic|Likely benign|Benign|Uncertain significance|VUS|Likely oncogenic|Oncogenic|Likely neutral|Neutral|Inconclusive)(?![A-Za-z])'


def _provider_page(provider,url):
    try:
        _portal_url(url)
        return urlsplit(url).hostname in PORTAL_HOSTS.get(provider,set())
    except (TypeError,ValueError):return False


def login_status(provider,snapshot):
    """An open window or a saved profile does not prove a current login."""
    result={'status':'unknown','summary':'Innlogging ikke bekreftet','checked_at':datetime.now(timezone.utc).isoformat()}
    url=snapshot.get('url','')
    if not url:return {**result,'reason':'snapshot_unavailable'}
    if not _provider_page(provider,url):return {**result,'reason':'unsafe_page'}
    parts=urlsplit(url)
    if snapshot.get('password_visible') or re.search(r'/(?:login|sign-?in|auth|log-?out|sign-?out)(?:/|$)',parts.path,re.I):
        return {**result,'status':'logged_out','summary':'Ikke innlogget'}
    if snapshot.get('logout_visible'):
        return {**result,'status':'logged_in','summary':'Innlogget'}
    if provider=='franklin' and parts.path.startswith('/clinical-db/') and snapshot.get('franklin_search'):
        return {**result,'status':'logged_in','summary':'Innlogget'}
    if provider=='mtbp' and parts.path.rstrip('/')=='/analyse' and snapshot.get('mtbp_form'):
        return {**result,'status':'logged_in','summary':'Innlogget'}
    if snapshot.get('login_visible'):
        return {**result,'status':'logged_out','summary':'Ikke innlogget'}
    return {**result,'reason':'no_auth_markers'}


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


class _BrowserConnectionClosed(RuntimeError):pass


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
        self._closed_error=websocket.WebSocketConnectionClosedException
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
            if self._socket is None:raise _BrowserConnectionClosed('Edge-forbindelsen er lukket.')
            self._counter+=1;identifier=self._counter
            message={'id':identifier,'method':method,'params':params or {}}
            if session_id:message['sessionId']=session_id
            try:self._socket.send(json.dumps(message,separators=(',',':')))
            except self._closed_error:raise _BrowserConnectionClosed('Edge-forbindelsen ble lukket.') from None
            except self._connection_error:raise RuntimeError('Edge-forespørselen kunne ikke sendes.') from None
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                self._socket.settimeout(max(.01,deadline-time.monotonic()))
                try:raw=self._socket.recv()
                except (TimeoutError,self._timeout_error):raise TimeoutError('Edge svarte ikke innen tidsgrensen.') from None
                except self._closed_error:raise _BrowserConnectionClosed('Edge-forbindelsen ble lukket.') from None
                except self._connection_error:raise RuntimeError('Edge-vinduet eller forbindelsen ble lukket.') from None
                if not raw:raise _BrowserConnectionClosed('Edge-forbindelsen ble lukket.')
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
    def snapshot(self,*,auth_only=False):
        text_field='' if auth_only else "text:(document.body?document.body.innerText:'').slice(0,120000),"
        return self.evaluate("""(()=>{
          const visible=x=>{
            const style=getComputedStyle(x),bounds=x.getBoundingClientRect();
            return style.display!=='none'&&style.visibility!=='hidden'&&style.visibility!=='collapse'&&
              Number(style.opacity)>0&&bounds.width>0&&bounds.height>0;
          };
          const controls=Array.from(document.querySelectorAll('a,button,[role=button],[role=menuitem]')).filter(visible);
          const caption=x=>(x.innerText||x.getAttribute('aria-label')||'').trim();
          return {url:location.href,"""+text_field+"""
            password_visible:Array.from(document.querySelectorAll('input[type=password]')).some(visible),
            franklin_search:Array.from(document.querySelectorAll("input[placeholder='Enter variant, gene or select an example above']")).some(visible),
            mtbp_form:Array.from(document.querySelectorAll('#variant-input')).some(visible),
            logout_visible:controls.some(x=>/^(?:log\\s*out|sign\\s*out|logout)$/i.test(caption(x))),
            login_visible:controls.some(x=>/^(?:log\\s*in|sign\\s*in|login)$/i.test(caption(x)))};
        })()""")

    def auth_snapshot(self):return self.snapshot(auth_only=True)

    def capture_png(self,path):
        result=self._connection.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False,'fromSurface':True},session_id=self._session)
        value=result.get('data','')
        if not isinstance(value,str) or len(value)>28_000_000:raise ValueError('Databasebildet er for stort.')
        image=base64.b64decode(value,validate=True)
        if not image.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Ugyldig databasebilde.')
        Path(path).write_bytes(image)

    def fill_login(self,provider,email,password):
        hosts=json.dumps(sorted(PORTAL_HOSTS[provider]))
        # Recheck the destination in-page: navigation can race an earlier probe.
        return self.evaluate("""(()=>{
          const allowed="""+hosts+""";
          if(location.protocol!=='https:'||!allowed.includes(location.hostname)||(location.port&&location.port!=='443'))return false;
          const visible=e=>e&&e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0&&getComputedStyle(e).visibility!=='hidden';
          const passwords=[...document.querySelectorAll('input[type=password]')].filter(visible);
          if(passwords.length!==1)return false;
          const p=passwords[0],form=p.form;if(!form)return false;
          const users=[...form.querySelectorAll('input[type=email],input[name=username],input[name=email],#email,#username,input[autocomplete=username],input[placeholder="Registered email address"],input[placeholder="Your institutional email address"]')].filter(visible);
          const unique=[...new Set(users)];if(unique.length!==1)return false;
          const target=new URL(form.action||location.href,location.href);
          if(target.protocol!=='https:'||!allowed.includes(target.hostname)||(target.port&&target.port!=='443'))return false;
          if(form.querySelector('input[type=checkbox][required]:not(:checked)')||/captcha|verify you are human/i.test(form.innerText))return false;
          const submit=[...form.querySelectorAll('button,input[type=submit]')].find(e=>visible(e)&&/^(sign in|log in|login|sign-in)$/i.test((e.innerText||e.value||'').trim()));
          if(!submit)return false;
          const action=new URL(submit.formAction||form.action||location.href,location.href);
          if(action.protocol!=='https:'||!allowed.includes(action.hostname)||(action.port&&action.port!=='443'))return false;
          const set=(e,v)=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));};
          set(unique[0],"""+json.dumps(email)+""");set(p,"""+json.dumps(password)+""");if(submit.disabled)return false;if(form.method.toLowerCase()!=='post')return true;submit.click();return true;
        })()""")

    def is_alive(self):
        """True/False require a completed target probe; None is inconclusive."""
        if self._connection is None:return False
        try:
            targets=self._connection.call('Target.getTargets',timeout=3).get('targetInfos',[])
            pages=[t for t in targets if isinstance(t,dict) and t.get('type')=='page']
            if any(t.get('targetId')==self._target for t in pages):return True
            # SSO can replace the original tab. Only consider provider pages
            # reported by this app-owned browser connection, never other profiles.
            replacement=next((t for t in pages if t.get('targetId') and _provider_page(self.profile.name,t.get('url',''))),None)
            if replacement is None:return None if pages else False
            session=self._connection.call('Target.attachToTarget',{'targetId':replacement['targetId'],'flatten':True},timeout=3)['sessionId']
            self._connection.call('Page.enable',session_id=session,timeout=3)
            self._target=replacement['targetId'];self._session=session
            return True
        except _BrowserConnectionClosed:return False
        except (OSError,RuntimeError,TimeoutError,ValueError):return None

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
        self._contexts={};self._confirmations={};self._locks={p:threading.RLock() for p in PORTAL_HOSTS};self._closed=False
        from .credentials import CredentialStore
        self.credentials=CredentialStore(self.data_dir)
        atexit.register(self.close)
    def set_credentials(self,credentials):self.credentials=credentials

    def _saved_login(self,provider,context):
        from .credentials import CredentialStoreError
        if not hasattr(context,'fill_login'):return False
        try:email,password=self.credentials.get(provider)
        except CredentialStoreError:return False
        if not email or not password:return False
        for attempt in range(12):
            if context.fill_login(provider,email,password):return True
            if self.status(provider).get('status')=='logged_in':return True
            time.sleep(.4)
        return False
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
        if existing is not None and hasattr(existing,'is_alive') and existing.is_alive() is False:self._discard(provider)
        if provider not in self._contexts:self._contexts[provider]=self._context_factory(executable,self.profile_dir/provider)
        return self._contexts[provider]

    def _discard(self,provider):
        self._confirmations.pop(provider,None)
        existing=self._contexts.pop(provider,None)
        if existing:
            try:existing.close()
            except (OSError,RuntimeError,TimeoutError):pass

    def _record_status(self,provider,context,result):
        state=result['status']
        if state=='logged_in':
            self._confirmations[provider]=(context,result['checked_at'])
            return {**result,'confirmed_at':result['checked_at']}
        if state=='logged_out' or result.get('reason')=='unsafe_page':
            self._confirmations.pop(provider,None)
            return result
        previous=self._confirmations.get(provider)
        if state=='unknown' and previous and previous[0] is context:
            confirmed=previous[1]
            clock=datetime.fromisoformat(confirmed).astimezone().strftime('%H:%M')
            return {**result,'status':'last_confirmed','summary':'Innlogget · sist bekreftet '+clock,'confirmed_at':confirmed}
        return result

    def status(self,provider):
        if provider not in LOGIN_URLS:return {'status':'public','summary':'Åpen kilde'}
        with self._locks[provider]:
            checked=datetime.now(timezone.utc).isoformat()
            context=self._contexts.get(provider)
            if context is None:
                self._confirmations.pop(provider,None)
                return {'status':'closed','summary':'Vindu lukket','checked_at':checked}
            try:
                alive=context.is_alive() if hasattr(context,'is_alive') else True
                if alive is False:
                    self._discard(provider);return {'status':'closed','summary':'Vindu lukket','checked_at':checked}
                if alive is None:
                    result={'status':'unknown','summary':'Innlogging ikke bekreftet','reason':'connection_unavailable'}
                else:
                    snapshot=context.auth_snapshot() if hasattr(type(context),'auth_snapshot') else context.snapshot()
                    result=login_status(provider,snapshot or {})
            except (OSError,RuntimeError,TimeoutError,ValueError):
                result={'status':'unknown','summary':'Innlogging ikke bekreftet','reason':'snapshot_unavailable'}
            return self._record_status(provider,context,{**result,'checked_at':checked})

    def open_login(self,provider):
        if provider not in LOGIN_URLS:raise ValueError('Kilden har ingen portalinnlogging.')
        with self._locks[provider]:
            context=self._context(provider)
            if self.status(provider).get('status') not in {'logged_in','last_confirmed'}:
                context.navigate(LOGIN_URLS[provider]);self._saved_login(provider,context)
            if hasattr(context,'bring_to_front'):context.bring_to_front()
    def open_url(self,url):
        checked_url(url);host=urlsplit(url).hostname
        provider=next((p for p,hosts in PORTAL_HOSTS.items() if host in hosts),None)
        if provider:
            with self._locks[provider]:return self._context(provider).navigate(url)
        return self.edge.open_url(url)

    def _capture(self,provider,variant,context,result):
        from .workflow import allele_key
        if not hasattr(context,'capture_png'):return {**result,'screenshot_error':'Nettleseren støtter ikke bildeuttak.'}
        root=self.data_dir/'evidence/databases'/allele_key(variant);root.mkdir(parents=True,exist_ok=True)
        path=root/(provider+'-'+uuid.uuid4().hex+'.png')
        try:
            context.capture_png(path)
            snapshot=context.snapshot() or {}
            if provider in PUBLIC_HOSTS:
                valid=self._public_identity(provider,variant,snapshot)
            else:valid=parse_portal_snapshot(provider,variant,snapshot).get('identity_verified') is True
            if not valid:
                path.unlink(missing_ok=True)
                return {**result,'screenshot_error':'Siden ble endret under bildeuttaket.'}
            return {**result,'screenshot':str(path),'identity_verified':True}
        except (OSError,ValueError,RuntimeError,TimeoutError):
            path.unlink(missing_ok=True)
            return {**result,'screenshot_error':'Databasebildet kunne ikke hentes.'}

    @staticmethod
    def _public_identity(provider,variant,snapshot):
        if not _provider_page(provider,snapshot.get('url','')) or snapshot.get('password_visible'):return False
        compact=re.sub(r'\s+','',unquote(str(snapshot.get('text',''))))
        identity=canonical_identity(variant)
        if provider=='clinvar':return genomic_hgvs(variant) in compact
        needle=f"{identity['chrom']}-{identity['pos']}-{identity['ref']}-{identity['alt']}"
        parts=urlsplit(snapshot.get('url',''))
        return parts.path=='/variant/'+needle and parse_qs(parts.query).get('dataset')==['gnomad_r2_1'] and needle in compact and bool(re.search(r'GRCh37|hg19',compact))

    def capture_result(self,provider,variant,result):
        if result.get('status')!='found' or provider not in PUBLIC_HOSTS:return result
        url=result.get('url','')
        if not _provider_page(provider,url):return {**result,'screenshot_error':'Uventet kildeadresse.'}
        with self._locks[provider]:
            try:
                context=self._context(provider);context.navigate(url)
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if self._public_identity(provider,variant,context.snapshot() or {}):return self._capture(provider,variant,context,result)
                    time.sleep(.5)
            except (OSError,ValueError,RuntimeError,TimeoutError):pass
        return {**result,'screenshot_error':'Nettsiden kunne ikke bekrefte allelet for bildet.'}
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
                snapshot=context.snapshot() or {}
                self._record_status(provider,context,login_status(provider,snapshot))
                result=parse_portal_snapshot(provider,variant,snapshot)
                if result['status']=='found':return self._capture(provider,variant,context,result)
                if result['status'] in {'not_found','login_required','license_required'}:return result
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
        self._confirmations.clear()
    shutdown=close
