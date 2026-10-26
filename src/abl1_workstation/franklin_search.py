"""Franklin's hg19/Somatic home search, using the same controls as Archer."""
import json
from .browser_evidence import evaluate
from .lookup import canonical_identity


def start_query(context,variant):
    identity=canonical_identity(variant)
    query=f"chr{identity['chrom']}-{identity['pos']}-{identity['ref']}-{identity['alt']}"
    state=evaluate(context,'franklin',r"""
      if(location.pathname.replace(/\/$/,'')!=='/clinical-db/home')return 'waiting';
      const input=[...document.querySelectorAll("input[placeholder='Enter variant, gene or select an example above']")].filter(visible);
      const selects=[...document.querySelectorAll('[role=combobox]')].filter(visible);
      if(input.length!==1||selects.length<2)return 'waiting';
      for(const [index,label] of [[0,'hg19'],[1,'Somatic']]){
        const control=selects[index];
        if(control.innerText.toLowerCase().includes(label.toLowerCase()))continue;
        const options=[...document.querySelectorAll('[role=option]')].filter(e=>visible(e)&&e.innerText.trim().toLowerCase()===label.toLowerCase());
        if(options.length===1)options[0].click();
        else if(control.getAttribute('aria-expanded')!=='true')control.click();
        return 'waiting';
      }
      const element=input[0];if(element.closest('form')&&new URL(element.form.action||location.href,location.href).origin!==location.origin)return 'waiting';
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(element,"""+json.dumps(query)+""");
      element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));
      element.focus();return 'ready';""")
    if state!='ready':return False
    context._page_call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13,'text':'\r','unmodifiedText':'\r'})
    context._page_call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
    return True


def resolve_option(context):
    return evaluate(context,'franklin',r"""
      if(location.pathname.replace(/\/$/,'')!=='/clinical-db/home')return false;
      const options=[...document.querySelectorAll('.option')].filter(visible);
      const matches=options.filter(e=>/\bNM_005157(?:\.\d+)?\b/.test(e.innerText));
      const selected=matches.length===1?matches[0]:(options.length===1?options[0]:null);
      if(!selected||selected.closest('form'))return false;
      selected.click();return true;""")
