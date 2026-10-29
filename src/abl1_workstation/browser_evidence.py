"""Read-only evidence views through the installed Edge, following Archer's selectors.

Actions are limited to known result tabs, evidence cards and cookie rejection.
No consent, CAPTCHA, account or report-creation control is clicked here.
"""
import json,math,time
from urllib.parse import urlsplit,urlunsplit

HOSTS={'clinvar':['www.ncbi.nlm.nih.gov'],
       'franklin':['franklin.genoox.com'],'oncokb':['www.oncokb.org'],
       'mtbp':['mtbp.org']}
VISIBLE="""const visible=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity)>0;};"""


def evaluate(context,provider,body):
    return context.evaluate("(()=>{if(location.protocol!=='https:'||!"+json.dumps(HOSTS[provider])+".includes(location.hostname)||location.port||location.username||location.password)throw Error('Unexpected source page');"+VISIBLE+body+"})()")


def dismiss_cookies(context,provider):
    # Only reject optional cookies inside known cookie containers. Never hide
    # arbitrary dialogs or accept terms on behalf of the user.
    clicked=evaluate(context,provider,"""
      const ids={franklin:'#CybotCookiebotDialogBodyButtonDecline',oncokb:'#onetrust-reject-all-handler'};
      const specific=ids["""+json.dumps(provider)+"""];
      if(specific){const buttons=[...document.querySelectorAll(specific)].filter(visible);
        if(buttons.length===1&&/^(Deny|Reject all|Accept essential)$/i.test(buttons[0].innerText.trim())&&!buttons[0].disabled){buttons[0].click();return true;}}
      const selectors='#onetrust-banner-sdk,#onetrust-consent-sdk,[class*=cookie-consent],[class*=consent-banner]';
      for(const box of document.querySelectorAll(selectors)){
        if(!visible(box))continue;
        const buttons=[...box.querySelectorAll('button')].filter(visible);
        const reject=buttons.filter(e=>/^(Reject all|Only necessary|Accept necessary|Accept essential)$/i.test(e.innerText.trim()));
        if(reject.length===1&&!reject[0].disabled){reject[0].click();return true;}
      }return false;""")
    if clicked:time.sleep(.35)
    blocked=evaluate(context,provider,"""
      return [...document.querySelectorAll('#onetrust-banner-sdk,#CybotCookiebotDialog,[class*=cookie-consent],[class*=consent-banner]')]
        .some(e=>visible(e)&&/cookie|privacy/i.test(e.innerText)&&[...e.querySelectorAll('button')].some(visible));""")
    if blocked:raise RuntimeError('Et cookie-vindu dekker resultatet. Lukk det i Edge og hent bildene igjen.')


def activate(context,label):
    if label not in ('Computed Classification','ACMG Classification','Oncogenic Classification'):raise ValueError('Ukjent resultatfane.')
    point=evaluate(context,'franklin',r"""
      if(!/\/clinical-db\/variant\/snp(?:Tumor)?\//.test(location.pathname))return false;
      const label="""+json.dumps(label)+""";
      let matches=[...document.querySelectorAll('[role=tab]')].filter(e=>visible(e)&&e.innerText.trim()===label);
      if(!matches.length)matches=[...document.querySelectorAll('span,div')].filter(e=>visible(e)&&e.innerText.trim()===label&&e.children.length===0);
      if(matches.length!==1)return false;
      const node=matches[0];if(node.closest('form'))return false;
      const target=node.getAttribute('role')==='tab'?node:node.parentElement;
      target.scrollIntoView({block:'nearest'});const r=target.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};""")
    if not isinstance(point,dict) or set(point)!={'x','y'}:return False
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=10000 for v in point.values()):return False
    for kind in ('mousePressed','mouseReleased'):
        context._page_call('Input.dispatchMouseEvent',{'type':kind,**point,'button':'left','clickCount':1})
    return True


def wait_panel(context,selector):
    for _ in range(20):
        if evaluate(context,'franklin',"return [...document.querySelectorAll("+json.dumps(selector)+")].some(visible);"):return
        time.sleep(.25)
    raise RuntimeError('Resultatpanelet ble ikke klart.')


def overview_clip(context,provider):
    if provider!='clinvar':return None
    return evaluate(context,provider,"""
      const nodes=[document.querySelector('main div.functions-container'),document.querySelector('#germline-somatic-info')];
      if(nodes.some(e=>!e||!visible(e)))return null;
      const boxes=nodes.map(e=>e.getBoundingClientRect());
      const x=Math.max(0,Math.min(...boxes.map(r=>r.left))-16)+scrollX;
      const y=Math.max(0,Math.min(...boxes.map(r=>r.top))-16)+scrollY;
      return {x,y,width:Math.min(1600,Math.max(...boxes.map(r=>r.right))+scrollX-x+16),height:Math.max(...boxes.map(r=>r.bottom))+scrollY-y+16};""")


def page_views(context,provider):
    """Readable page tiles avoid both a clipped summary and a giant bitmap.

    The original page is retained. Each tile overlaps its predecessor so rows
    crossing the boundary can be read in the next image. A very large page
    produces explicit partial-capture status after the bounded number of tiles.
    """
    if provider not in ('clinvar','oncokb'):raise ValueError('Ukjent sideuttrekk.')
    title='ClinVar' if provider=='clinvar' else 'OncoKB'
    size=evaluate(context,provider,"""
      return {width:Math.max(document.documentElement.clientWidth,document.documentElement.scrollWidth),
              height:Math.max(document.documentElement.scrollHeight,document.body?.scrollHeight||0)};""")
    if (not isinstance(size,dict) or any(isinstance(size.get(k),bool) or not isinstance(size.get(k),(int,float))
            or not math.isfinite(size[k]) for k in ('width','height'))):raise RuntimeError(title+'-sidens størrelse kunne ikke leses.')
    width=math.ceil(size['width']);height=math.ceil(size['height'])
    if not 200<=width<=4000 or height<80:raise RuntimeError(title+'-siden har uventede dimensjoner.')
    y=0
    for index in range(32):
        tile_height=min(1200,height-y)
        if tile_height<80:y=max(0,height-80);tile_height=height-y
        yield title+' page · section '+str(index+1),{'x':0,'y':y,'width':width,'height':tile_height}
        if y+tile_height>=height:return
        y+=tile_height-80
    raise RuntimeError(title+'-siden overstiger 32 bildeseksjoner; bildeuttrekket er avkortet.')


def card_view(context,selector,index):
    # Archer renders an exact DOM clone outside the internal clipping scroller.
    # Keep the original content/styles; always remove the temporary wrapper.
    return evaluate(context,'franklin',"""
      const nodes=[...document.querySelectorAll("""+json.dumps(selector)+""")].filter(visible);
      const node=nodes["""+str(index)+"""];if(!node)throw Error('Evidence card unavailable');
      const old=document.getElementById('dragen-evidence-capture');if(old)old.remove();
      const wrapper=document.createElement('div');wrapper.id='dragen-evidence-capture';
      const rect=node.getBoundingClientRect();
      Object.assign(wrapper.style,{position:'absolute',left:'0px',top:`${scrollY}px`,width:`${Math.ceil(rect.width)}px`,height:'auto',minHeight:'84px',padding:'16px',boxSizing:'border-box',overflow:'visible',background:'white',zIndex:'2147483647',pointerEvents:'none'});
      const clone=node.cloneNode(true);
      Object.assign(clone.style,{display:'block',width:'100%',height:'auto',maxHeight:'none',overflow:'visible',margin:'0'});
      wrapper.appendChild(clone);document.body.appendChild(wrapper);
      const box=wrapper.getBoundingClientRect();
      return {x:box.x+scrollX,y:box.y+scrollY,width:Math.ceil(box.width),height:Math.ceil(box.height)};""")


def classification_views(context,label,panel,categories):
    if not activate(context,label):raise RuntimeError('Klassifikasjonsfanen finnes ikke.')
    wait_panel(context,panel);time.sleep(.25)
    yield label+' overview',None
    titles=evaluate(context,'franklin',"return [...document.querySelectorAll("+json.dumps(categories)+")].filter(visible).map(e=>(e.innerText||'').trim().split('\\n')[0].slice(0,120));") or []
    if not titles:raise RuntimeError('Evidenskortene kunne ikke leses.')
    for index,title in enumerate(titles[:24]):
        try:
            clip=card_view(context,categories,index)
            yield label+' evidence: '+str(title or index+1),clip
        finally:evaluate(context,'franklin',"document.getElementById('dragen-evidence-capture')?.remove();return true;")
    if len(titles)>24:raise RuntimeError('Flere enn 24 evidenskort; bildeuttrekket er avkortet.')


def evidence_views(context,provider):
    context._page_call('Emulation.setDeviceMetricsOverride',{'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
    dismiss_cookies(context,provider);time.sleep(.25)
    if provider in ('clinvar','oncokb'):
        yield from page_views(context,provider)
        return
    yield 'Variant overview',None
    if provider!='franklin':return
    initial=context.snapshot() or {};original_url=initial.get('url','')
    failures=[]
    try:
        if activate(context,'Computed Classification'):
            for _ in range(32):
                ready=evaluate(context,'franklin',"return [...document.querySelectorAll('span,div')].some(e=>visible(e)&&e.children.length===0&&e.innerText.trim()==='ACMG Classification');")
                if ready:break
                time.sleep(.25)
        for args in (('ACMG Classification','gnx-result-page','gnx-result-page gnx-result-category'),
                     ('Oncogenic Classification','gnx-oncogenic-classification-app','gnx-oncogenic-classification-app gnx-oncogenic-classification-tile')):
            try:yield from classification_views(context,*args)
            except (OSError,ValueError,RuntimeError,TimeoutError):failures.append(args[0])
        parts=urlsplit(original_url)
        if parts.hostname=='franklin.genoox.com' and '/clinical-db/variant/' in parts.path:
            context.navigate(urlunsplit((parts.scheme,parts.netloc,parts.path,'app=assessment-tools','')))
            for _ in range(24):
                ready=evaluate(context,'franklin',"return [...document.querySelectorAll('h1,h2,h3,h4,[role=heading]')].filter(visible).some(e=>e.innerText.trim()==='Predictions');")
                if ready:break
                time.sleep(.25)
            for label in ('Predictions','Population Frequencies','Transcripts and References'):
                found=evaluate(context,'franklin',"""
                  const heading=[...document.querySelectorAll('h1,h2,h3,h4,[role=heading]')].filter(visible).find(e=>e.innerText.trim()==="""+json.dumps(label)+""");
                  if(!heading)return false;heading.scrollIntoView({block:'start'});window.scrollBy(0,-24);return true;""")
                if found:time.sleep(.25);yield label,None
                else:failures.append(label)
    finally:
        # Never move a page that the user navigated away from during capture.
        current=context.snapshot() or {}
        if urlsplit(current.get('url','')).path==urlsplit(original_url).path:context.navigate(original_url)
    if failures:raise RuntimeError('Noen Franklin-visninger mangler: '+', '.join(failures))
