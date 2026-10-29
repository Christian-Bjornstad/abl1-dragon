"""Franklin's hg19/Somatic home search, using the same controls as Archer."""
import json
from .browser_evidence import evaluate,dismiss_cookies
from .lookup import canonical_identity


def _click(context,point):
    if not isinstance(point,dict) or set(point)!={'x','y'}:return False
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not 0<=v<=10000 for v in point.values()):return False
    context._page_call('Input.dispatchMouseEvent',{'type':'mousePressed',**point,'button':'left','clickCount':1})
    context._page_call('Input.dispatchMouseEvent',{'type':'mouseReleased',**point,'button':'left','clickCount':1})
    return True


def start_query(context,variant):
    dismiss_cookies(context,'franklin')
    # Same optional first-use skip as Archer/Solide. Never choose material,
    # consent, terms or a clinical context on the user's behalf.
    evaluate(context,'franklin',r"""
      for(const box of document.querySelectorAll('[role=dialog],[aria-modal=true],.mat-dialog-container,.mat-mdc-dialog-container,.cdk-overlay-pane')){
        if(!visible(box)||!/\b(?:sample (?:type|material)|material|tissue|phenotype|first (?:analysis|time)|get(?:ting)? started)\b/i.test(box.innerText))continue;
        const skip=[...box.querySelectorAll('button')].filter(e=>visible(e)&&/^(skip|skip for now)$/i.test(e.innerText.trim()));
        if(skip.length===1&&!skip[0].disabled){skip[0].click();return true;}
      }return false;""")
    identity=canonical_identity(variant)
    query=f"chr{identity['chrom']}-{identity['pos']}-{identity['ref']}-{identity['alt']}"
    state=evaluate(context,'franklin',r"""
      if(location.pathname.replace(/\/$/,'')!=='/clinical-db/home')return 'waiting';
      const input=[...document.querySelectorAll("input[placeholder='Enter variant, gene or select an example above']")].filter(visible);
      const selects=[...document.querySelectorAll('[role=combobox]')].filter(visible);
      if(input.length!==1||selects.length<2)return 'waiting';
      for(const [index,label] of [[0,'hg19'],[1,'Somatic']]){
        const control=selects[index];
        const value=control.querySelector('.mat-mdc-select-value')||control;
        if(value.innerText.trim().toLowerCase()===label.toLowerCase())continue;
        const options=[...document.querySelectorAll('[role=option]')].filter(e=>visible(e)&&e.innerText.trim().toLowerCase()===label.toLowerCase());
        const target=options.length===1?options[0]:(control.getAttribute('aria-expanded')!=='true'?control:null);
        if(target){target.scrollIntoView({block:'nearest'});const r=target.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};}
        return 'waiting';
      }
      const element=input[0];if(element.closest('form')&&new URL(element.form.action||location.href,location.href).origin!==location.origin)return 'waiting';
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(element,"""+json.dumps(query)+""");
      element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));
      element.focus();return 'ready';""")
    if isinstance(state,dict):_click(context,state);return False
    if state!='ready':return False
    context._page_call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13,'text':'\r','unmodifiedText':'\r'})
    context._page_call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
    return True


def resolve_option(context):
    point=evaluate(context,'franklin',r"""
      if(location.pathname.replace(/\/$/,'')!=='/clinical-db/home')return false;
      const options=[...document.querySelectorAll('.option')].filter(visible);
      const matches=options.filter(e=>/\bNM_005157(?:\.\d+)?\b/.test(e.innerText));
      const selected=matches.length===1?matches[0]:(options.length===1?options[0]:null);
      if(!selected||selected.closest('form'))return false;
      selected.scrollIntoView({block:'nearest'});const r=selected.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};""")
    return _click(context,point)
