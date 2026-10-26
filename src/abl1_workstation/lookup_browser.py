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
ACTIVE_CHALLENGE=r'access denied|verify (?:that )?you are (?:a )?human|checking your browser|complete (?:the )?(?:security|captcha)|(?:^|\n)\s*CAPTCHA\s*(?:$|[:!?])'


def _manual_check(snapshot):
    # Passive "protected by reCAPTCHA" badges are present on valid results.
    return snapshot.get('challenge_visible') is True or bool(re.search(ACTIVE_CHALLENGE,str(snapshot.get('text','')),re.I))


def _provider_page(provider,url):
    try:
        _portal_url(url)
        return urlsplit(url).hostname in PORTAL_HOSTS.get(provider,set())
    except (TypeError,ValueError):return False


def _clinvar_record_path(url):
    if not _provider_page('clinvar',url):return None
    path=urlsplit(url).path
    return path.rstrip('/') if re.fullmatch(r'/clinvar/variation/[0-9]+/?',path) else None


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
    if provider=='oncokb' and snapshot.get('oncokb_account_visible') is True:
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
    if _manual_check(snapshot):
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
    readable_page=(provider=='oncokb' and snapshot.get('oncokb_result_visible') is True
                   and 'Clinical Implications for this Biomarker' in text)
    if provider!='cosmic' and not classifications and not readable_page:return result
    levels=_labelled_levels(text)
    excerpt=[label+': '+value for label,value in classifications+levels]
    classification='; '.join(label+': '+value for label,value in classifications) if provider=='franklin' else '; '.join(value for _,value in classifications)
    summary=(' | '.join(excerpt[:8]) if excerpt else 'COSMIC oversikt og kildeinnhold er tilgjengelig.')
    if readable_page and not classifications:
        summary='Klassifikasjonen kunne ikke leses automatisk. Se variantens kildebilde og lenke.'
    return {**result,'status':'found','classification':classification,'evidence_level':'; '.join(label+': '+value for label,value in levels),
            'summary':f'{provider.title()}: identitetskontrollert portalresultat. '+summary,
            'identity_verified':True,'identity_method':identity_method,
            'accession':genomic_hgvs(variant),'classifications':{label:{'description':value} for label,value in classifications},
            'details':{'portal_excerpt':excerpt[:12],'retrieval':'visible authenticated portal content'}}


class _BrowserConnectionClosed(RuntimeError):pass
class _BrowserTargetClosed(RuntimeError):pass


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
            except (ConnectionError,self._closed_error):raise _BrowserConnectionClosed('Edge-forbindelsen ble lukket.') from None
            except self._connection_error:raise RuntimeError('Edge-forespørselen kunne ikke sendes.') from None
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                self._socket.settimeout(max(.01,deadline-time.monotonic()))
                try:raw=self._socket.recv()
                except (TimeoutError,self._timeout_error):raise TimeoutError('Edge svarte ikke innen tidsgrensen.') from None
                except (ConnectionError,self._closed_error):raise _BrowserConnectionClosed('Edge-forbindelsen ble lukket.') from None
                except self._connection_error:raise RuntimeError('Edge-vinduet eller forbindelsen ble lukket.') from None
                if not raw:raise _BrowserConnectionClosed('Edge-forbindelsen ble lukket.')
                if len(raw)>8*1024*1024:raise RuntimeError('Edge-svaret er for stort.')
                response=json.loads(raw)
                if response.get('id')!=identifier:continue
                if 'error' in response:
                    message=str((response.get('error') or {}).get('message',''))
                    if re.search(r'no session with given id|session with given id not found|session (?:is )?closed|no target with given id|target closed|not attached to an active page',message,re.I):
                        raise _BrowserTargetClosed('Portalens fane eller kontrolløkt ble lukket.')
                    raise RuntimeError('Edge avviste portalforespørselen.')
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


def _acquire_profile_lease(profile):
    """An OS lease survives neither app crashes nor process termination.

    Keep the file: deleting it can let two processes lock different inodes.
    Its contents are never used as authority to attach to a browser.
    """
    lease=None
    try:
        path=Path(profile)/'.abl1-portal.lock'
        if path.is_symlink():raise OSError('Profile lease is a link')
        lease=path.open('a+b')
        lease.seek(0,os.SEEK_END)
        if lease.tell()==0:lease.write(b'\0');lease.flush()
        lease.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(lease.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return lease
    except OSError:
        if lease is not None:lease.close()
        raise RuntimeError('Portalprofilen brukes av en annen appøkt. Lukk appens portalvindu og prøv igjen.') from None


def _clear_stale_endpoint(profile):
    """Remove an old marker only on a positively refused loopback listener.

    Never attach to an old browser, delete uncertain markers, or inspect any
    ordinary user profile. A responsive or indeterminate listener is busy.
    """
    import socket
    marker=Path(profile)/'DevToolsActivePort'
    if not marker.exists():return
    try:
        if marker.resolve().parent!=Path(profile) or marker.is_symlink() or marker.stat().st_size>256:
            raise ValueError('Invalid profile marker')
        original=marker.read_bytes();lines=original.decode('utf-8').splitlines()
        if (len(lines)!=2 or not lines[0].isdigit() or not 1024<=int(lines[0])<=65535
                or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]{16,80}',lines[1])):
            raise ValueError('Invalid profile marker')
        try:transport=socket.create_connection(('127.0.0.1',int(lines[0])),timeout=3)
        except ConnectionRefusedError:
            # Do not remove a newer marker written during the probe.
            if marker.read_bytes()!=original:raise ValueError('Profile marker changed')
            marker.unlink();return
        else:transport.close()
    except (OSError,ValueError,UnicodeError):
        raise RuntimeError('Portalprofilens tidligere Edge-forbindelse kunne ikke bekreftes lukket. Lukk bare appens portalvindu og prøv igjen.') from None
    raise RuntimeError('Appens tidligere portalvindu bruker fortsatt profilen. Lukk dette vinduet og prøv igjen.')


class _EdgeContext:
    def __init__(self,executable,profile):
        if sys.platform!='win32':raise RuntimeError('Portaloppslag krever Windows/Edge.')
        self.profile=Path(profile);self.profile.mkdir(parents=True,exist_ok=True)
        if self.profile.resolve()!=self.profile:raise RuntimeError('Edge-profilen peker til en annen mappe.')
        self._lease_path=self.profile/'.abl1-portal.lock';self._lease=None;self._process=None;self._connection=None;self._startup_stderr=None
        self._lease=_acquire_profile_lease(self.profile)
        try:
            _clear_stale_endpoint(self.profile)
            self._startup_stderr=tempfile.TemporaryFile(mode='w+b')
            port_file=self.profile/'DevToolsActivePort'
            # Only the marker from this launch may authorize a connection.
            self._port_file=port_file;started=time.time_ns()
            args=[str(executable),'--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
                  '--user-data-dir='+str(self.profile),'--profile-directory=Default','--no-first-run',
                  '--no-default-browser-check','--disable-background-mode','--disable-sync',
                  '--disable-features=msEdgeStartupBoost,msImplicitSignin',
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
            raise RuntimeError(str(error)+' Edge startet ikke kontrollert portalforbindelse. Avslutningskode: '+str(code)+
                               ('. Oppstartslogg: '+str(diagnostic) if diagnostic else '')+'.') from error
    def _page_call(self,method,params=None,*,timeout=20):
        try:return self._connection.call(method,params,session_id=self._session,timeout=timeout)
        except _BrowserTargetClosed:
            if self.is_alive(refresh_session=True) is not True:raise
            return self._connection.call(method,params,session_id=self._session,timeout=timeout)

    def evaluate(self,expression):
        result=self._page_call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True,'userGesture':True})
        if result.get('exceptionDetails'):raise RuntimeError('Nettstedets oppslag kunne ikke utføres.')
        return (result.get('result') or {}).get('value')
    def navigate(self,url):
        _portal_url(url)
        self._page_call('Page.navigate',{'url':url})
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
          return {url:location.href,ready_state:document.readyState,
            page_busy:Array.from(document.querySelectorAll('[aria-busy=true]')).some(visible),"""+text_field+"""
            challenge_visible:Array.from(document.querySelectorAll('iframe[src*="/recaptcha/"][src*="/bframe"],iframe[title*="challenge" i]')).some(visible),
            password_visible:Array.from(document.querySelectorAll('input[type=password]')).some(visible),
            franklin_search:Array.from(document.querySelectorAll("input[placeholder='Enter variant, gene or select an example above']")).some(visible),
            mtbp_form:Array.from(document.querySelectorAll('#variant-input')).some(visible),
            oncokb_account_visible:location.hostname==='www.oncokb.org'&&Array.from(document.querySelectorAll('header #account-menu')).some(visible),
            oncokb_result_visible:location.hostname==='www.oncokb.org'&&Array.from(document.querySelectorAll('h1')).some(x=>visible(x)&&/\\bABL1\\b/.test(x.innerText||''))&&Array.from(document.querySelectorAll('#clinical-implications')).some(visible),
            logout_visible:controls.some(x=>/^(?:log\\s*out|sign\\s*out|logout)$/i.test(caption(x))),
            login_visible:controls.some(x=>/^(?:log\\s*in|sign\\s*in|login)(?:\\s*\\/\\s*register)?$/i.test(caption(x)))};
        })()""")

    def auth_snapshot(self):return self.snapshot(auth_only=True)

    def expand_clinvar_hgvs(self,expected_url):
        """Reveal ClinVar's hidden HGVS rows using only its read-only toggle.

        A trusted API result supplies the numeric record path. Recheck it in
        the page to protect against navigation between snapshot and click.
        """
        path=_clinvar_record_path(expected_url)
        if path is None:return False
        return self.evaluate("""(()=>{
          const page=new URL(location.href);
          if(page.protocol!=='https:'||page.hostname!=='www.ncbi.nlm.nih.gov'||page.port||page.username||page.password||page.pathname.replace(/\\/$/,'')!=="""+json.dumps(path)+""")return false;
          const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity)>0;};
          const controls=[...document.querySelectorAll('[id="hgvs_more"]')];
          if(controls.length!==1)return false;
          const control=controls[0];
          if(!visible(control)||control.tagName!=='A'||control.closest('form')||! /^(?:\\.{3}|…)?\\s*more\\s+HGVS$/i.test((control.innerText||'').trim()))return false;
          const href=(control.getAttribute('href')||'').trim();
          if(href&&!href.startsWith('#')&&!/^javascript:\\s*void\\(0\\);?$/i.test(href))return false;
          // The expected toggle only reveals text. Suppress its fragment/default
          // link action; never navigate or click a verification control.
          control.addEventListener('click',event=>event.preventDefault(),{once:true});
          control.click();return true;
        })()""")

    def capture_png(self,path):
        result=self._page_call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False,'fromSurface':True})
        value=result.get('data','')
        if not isinstance(value,str) or len(value)>28_000_000:raise ValueError('Databasebildet er for stort.')
        image=base64.b64decode(value,validate=True)
        if not image.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Ugyldig databasebilde.')
        Path(path).write_bytes(image)

    def fill_login(self,provider,email,password):
        hosts=json.dumps(sorted(PORTAL_HOSTS[provider]))
        # Recheck the destination in-page: navigation can race an earlier probe.
        return self.evaluate("""(async()=>{
          const allowed="""+hosts+""";
          const safe=u=>u.protocol==='https:'&&allowed.includes(u.hostname)&&!u.username&&!u.password&&(!u.port||u.port==='443');
          const origin=location.href;if(!safe(new URL(origin)))return false;
          const visible=e=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&Number(s.opacity)>0;};
          const passwords=[...document.querySelectorAll('input[type=password]')].filter(visible);
          if(passwords.length!==1)return false;
          const p=passwords[0];
          const reactLogin="""+json.dumps(provider=='oncokb')+"""&&new URL(origin).pathname.replace(/\\/$/,'')==='/login';
          const form=p.form||(reactLogin?p.closest('[role=form],.login-form,.login-container,.form-container'):null);
          if(!form)return false;
          const users=[...form.querySelectorAll('input[type=email],input[name=username],input[name=email],#email,#username,input[autocomplete=username],input[placeholder="Registered email address"],input[placeholder="Your institutional email address"]')].filter(visible);
          const unique=[...new Set(users)];if(unique.length!==1)return false;
          const target=new URL(form.action||location.href,location.href);
          if(!safe(target))return false;
          const activeChallenge=new RegExp("""+json.dumps(ACTIVE_CHALLENGE)+""",'i');
          if(form.querySelector('input[type=checkbox][required]:not(:checked)')||activeChallenge.test(form.innerText)||[...document.querySelectorAll('iframe[src*="/recaptcha/"][src*="/bframe"],iframe[title*="challenge" i]')].some(visible))return false;
          const buttons=[...form.querySelectorAll('button,input[type=submit]')].filter(e=>visible(e)&&/^(sign in|log in|login|sign-in)$/i.test((e.innerText||e.value||'').trim()));
          if(buttons.length!==1)return false;const submit=buttons[0];
          const action=new URL(submit.formAction||form.action||location.href,location.href);
          if(!safe(action))return false;
          const set=(e,v)=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));};
          set(unique[0],"""+json.dumps(email)+""");set(p,"""+json.dumps(password)+""");
          // React controlled inputs may enable the button in the next task.
          await new Promise(resolve=>setTimeout(resolve,0));
          if(location.href!==origin||!safe(new URL(submit.formAction||form.action||location.href,location.href))||submit.disabled||!visible(submit))return false;
          if(p.form&&String(form.method).toLowerCase()!=='post'){
            if(!reactLogin)return false;
            // OncoKB submits through React. Prevent a native GET fallback
            // from putting credentials in the address bar if JS changes.
            form.addEventListener('submit',event=>event.preventDefault(),{once:true});
          }
          submit.click();return true;
        })()""")

    def is_alive(self,*,refresh_session=False):
        """True/False require a completed target probe; None is inconclusive."""
        if self._connection is None:return False
        try:
            targets=self._connection.call('Target.getTargets',timeout=3).get('targetInfos',[])
            pages=[t for t in targets if isinstance(t,dict) and t.get('type')=='page']
            original=next((t for t in pages if t.get('targetId')==self._target),None)
            if original is not None and not refresh_session:return True
            # SSO can replace the original tab. Only consider provider pages
            # reported by this app-owned browser connection, never other profiles.
            replacement=original or next((t for t in pages if t.get('targetId') and _provider_page(self.profile.name,t.get('url',''))),None)
            if replacement is None:return None if pages else False
            session=self._connection.call('Target.attachToTarget',{'targetId':replacement['targetId'],'flatten':True},timeout=3)['sessionId']
            self._connection.call('Page.enable',session_id=session,timeout=3)
            self._target=replacement['targetId'];self._session=session
            return True
        except _BrowserConnectionClosed:return False
        except (OSError,RuntimeError,TimeoutError,ValueError):return None

    def bring_to_front(self):
        self._page_call('Page.bringToFront',timeout=3)

    def recover_target(self):
        """Explicit open/search may create a new tab in our owned browser.

        Status checks and manual screenshot resume must never call this: a
        missing target is not permission to claim an unrelated or SSO page.
        """
        try:
            targets=self._connection.call('Target.getTargets',timeout=3).get('targetInfos',[])
            pages=[t for t in targets if isinstance(t,dict) and t.get('type')=='page']
            if any(t.get('targetId')==self._target for t in pages):return False
            replacement=next((t['targetId'] for t in pages if t.get('targetId') and _provider_page(self.profile.name,t.get('url',''))),None)
            target=replacement or self._connection.call('Target.createTarget',{'url':'about:blank'},timeout=3)['targetId']
            session=self._connection.call('Target.attachToTarget',{'targetId':target,'flatten':True},timeout=3)['sessionId']
            self._connection.call('Page.enable',session_id=session,timeout=3)
            self._target=target;self._session=session
            return True
        except (OSError,RuntimeError,TimeoutError,ValueError,KeyError):return False

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
            try:_clear_stale_endpoint(self.profile)
            except (OSError,RuntimeError):pass
        if self._lease is not None:
            self._lease.close();self._lease=None
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
        if existing is not None and hasattr(existing,'is_alive'):
            alive=existing.is_alive()
            if alive is False:self._discard(provider)
            elif alive is None and hasattr(type(existing),'recover_target') and existing.recover_target():
                self._confirmations.pop(provider,None)
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
        if not hasattr(context,'capture_png'):return self._capture_error(result,'capture_unsupported','Nettleseren støtter ikke bildeuttak.')
        path=None
        try:
            problem=self._capture_problem(provider,variant,context.snapshot() or {})
            if problem:return self._capture_error(result,*problem)
            root=self.data_dir/'evidence/databases'/allele_key(variant);root.mkdir(parents=True,exist_ok=True)
            path=root/(provider+'-'+uuid.uuid4().hex+'.png')
            context.capture_png(path)
            snapshot=context.snapshot() or {}
            problem=self._capture_problem(provider,variant,snapshot)
            if problem:
                path.unlink(missing_ok=True)
                return self._capture_error(result,*problem)
            updated={**result,'screenshot':str(path),'identity_verified':True}
            updated.pop('screenshot_error',None);updated.pop('screenshot_reason',None)
            return updated
        except (OSError,ValueError,RuntimeError,TimeoutError):
            if path is not None:path.unlink(missing_ok=True)
            return self._capture_error(result,'capture_failed','Databasebildet kunne ikke hentes. Prøv «Hent bilder fra åpne sider» når siden er ferdig.')

    @staticmethod
    def _capture_error(result,reason,message):
        return {**result,'screenshot_error':message,'screenshot_reason':reason}

    @classmethod
    def _capture_problem(cls,provider,variant,snapshot):
        if not _provider_page(provider,snapshot.get('url','')):
            return 'unsafe_page','Nettsiden viser ikke den forventede databaseverten. Åpne kilden på nytt.'
        text=str(snapshot.get('text',''))
        if _manual_check(snapshot):
            return 'manual_check_required','Nettstedet krever manuell kontroll i appens Edge-vindu. Fullfør kontrollen og velg «Hent bilder fra åpne sider».'
        if snapshot.get('password_visible'):
            return 'login_required','Logg inn i appens Edge-vindu, åpne variantresultatet og velg «Hent bilder fra åpne sider».'
        if snapshot.get('ready_state','complete')!='complete' or snapshot.get('page_busy') is True:
            return 'page_not_ready','Databasesiden er ikke ferdig lastet. Vent og velg «Hent bilder fra åpne sider».'
        valid=(cls._public_identity(provider,variant,snapshot) if provider in PUBLIC_HOSTS
               else parse_portal_snapshot(provider,variant,snapshot).get('identity_verified') is True)
        if not valid:return 'identity_mismatch','Siden bekrefter ikke valgt GRCh37-allel. Åpne riktig variant og velg «Hent bilder fra åpne sider».'
        return None

    @staticmethod
    def _public_identity(provider,variant,snapshot):
        if not _provider_page(provider,snapshot.get('url','')) or snapshot.get('password_visible'):return False
        text=unquote(str(snapshot.get('text','')))
        compact=re.sub(r'\s+','',text)
        identity=canonical_identity(variant)
        if provider=='clinvar':
            hgvs=genomic_hgvs(variant)
            candidates=[hgvs]
            # ABL1's GRCh37 chromosome reference. ClinVar renders accession
            # HGVS, whereas the OncoKB query uses a chromosome-number prefix.
            # Never accept GRCh38 NC_000009.12 or infer a build from a position.
            if identity['chrom']=='9':candidates.append('NC_000009.11:'+hgvs.split(':',1)[1])
            return any(re.search(r'(?<![A-Za-z0-9_.])'+re.escape(value)+r'(?![A-Za-z0-9_>])',text) is not None for value in candidates)
        needle=f"{identity['chrom']}-{identity['pos']}-{identity['ref']}-{identity['alt']}"
        parts=urlsplit(snapshot.get('url',''))
        return parts.path=='/variant/'+needle and parse_qs(parts.query).get('dataset')==['gnomad_r2_1'] and needle in compact and bool(re.search(r'GRCh37|hg19',compact))

    def capture_result(self,provider,variant,result):
        if result.get('status')!='found' or provider not in PUBLIC_HOSTS:return result
        if not self._result_matches(provider,variant,result):
            return self._capture_error(result,'identity_mismatch','Databaseresultatet tilhører ikke valgt GRCh37-allel. Kjør oppslaget igjen.')
        url=result.get('url','')
        if not _provider_page(provider,url):return self._capture_error(result,'unsafe_page','Uventet kildeadresse.')
        with self._locks[provider]:
            try:
                context=self._context(provider);context.navigate(url)
                return self._wait_capture(provider,variant,context,result)
            except (OSError,ValueError,RuntimeError,TimeoutError):
                return self._capture_error(result,'connection_unavailable','Edge-forbindelsen er utilgjengelig. Åpne kilden på nytt og prøv igjen.')

    def _wait_capture(self,provider,variant,context,result):
        deadline=time.monotonic()+20;problem=None;expansion_attempted=False
        while time.monotonic()<deadline:
            snapshot=context.snapshot() or {}
            problem=self._capture_problem(provider,variant,snapshot)
            if not problem:
                if provider not in PUBLIC_HOSTS and result.get('status')!='found':
                    parsed=parse_portal_snapshot(provider,variant,snapshot)
                    if parsed.get('status')=='found' and parsed.get('identity_verified') is True:
                        result={**result,**parsed}
                return self._capture(provider,variant,context,result)
            if problem[0]=='login_required':break
            if provider=='clinvar' and problem[0]=='identity_mismatch' and not expansion_attempted:
                expected=_clinvar_record_path(result.get('url',''))
                if expected and expected==_clinvar_record_path(snapshot.get('url','')) and hasattr(context,'expand_clinvar_hgvs'):
                    expansion_attempted=True
                    context.expand_clinvar_hgvs(result['url'])
            # NCBI's automatic browser check often clears by itself. Passive
            # waiting stays inside the same budget and never solves a challenge.
            time.sleep(.5)
        return self._capture_error(result,*(problem or ('page_not_ready','Databasesiden ble ikke ferdig. Prøv «Hent bilder fra åpne sider».')))

    def recapture_result(self,provider,variant,result):
        """Resume capture after manual login/checks without navigating away.

        An API/text result stays intact. Never launch a browser implicitly or
        move the page the user just prepared; capture only this exact allele.
        """
        resumable=(provider in {'franklin','oncokb','cosmic'} and result.get('status') in {'login_required','error'})
        if provider not in PORTAL_HOSTS or provider=='mtbp' or (result.get('status')!='found' and not resumable):
            return self._capture_error(result,'capture_unsupported','Ingen identitetskontrollert variant klar for bildeuttak.')
        if not self._result_matches(provider,variant,result):
            return self._capture_error(result,'identity_mismatch','Databaseresultatet tilhører ikke valgt GRCh37-allel. Kjør oppslaget igjen.')
        with self._locks[provider]:
            context=self._contexts.get(provider)
            if context is None:return self._capture_error(result,'window_closed','Appens databasevindu er lukket. Åpne kilden, vis varianten og velg «Hent bilder fra åpne sider».')
            try:
                alive=context.is_alive() if hasattr(context,'is_alive') else True
                if alive is False:
                    self._discard(provider)
                    return self._capture_error(result,'window_closed','Appens databasevindu er lukket. Åpne kilden på nytt før bildeuttak.')
                if alive is None:return self._capture_error(result,'connection_unavailable','Edge-forbindelsen er ikke bekreftet. Vent eller åpne kilden på nytt.')
                return self._wait_capture(provider,variant,context,result)
            except (OSError,ValueError,RuntimeError,TimeoutError):
                return self._capture_error(result,'connection_unavailable','Edge-forbindelsen er utilgjengelig. Åpne kilden på nytt og prøv igjen.')

    @staticmethod
    def _result_matches(provider,variant,result):
        try:
            return (result.get('provider',provider)==provider
                    and canonical_identity(result.get('identity') or {})==canonical_identity(variant))
        except (TypeError,ValueError):return False

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
