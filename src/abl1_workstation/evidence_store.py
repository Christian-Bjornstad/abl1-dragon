"""Local per-allele evidence receipts, separate from samples and credentials."""
import json,os,tempfile
from pathlib import Path
from .lookup import canonical_identity,PROVIDERS,STATUSES
from .workflow import allele_key

FIELDS={'provider','status','summary','classification','evidence_level','accession','url','checked_at',
        'identity','identity_verified','identity_method','source_version','classifications','details',
        'screenshot','screenshots','captured_at','screenshot_error','screenshot_reason',
        'transcripts','proteins','reference_hgvs'}


class EvidenceStore:
    def __init__(self,data_dir):self.root=Path(data_dir).resolve()/'evidence/databases'

    def save(self,variant,result):
        identity=canonical_identity(variant);provider=result.get('provider')
        if provider not in PROVIDERS or result.get('status') not in STATUSES:raise ValueError('Ugyldig databaseresultat.')
        if canonical_identity(result.get('identity') or {})!=identity:raise ValueError('Feil variant i databaseresultat.')
        data={k:v for k,v in result.items() if k in FIELDS}
        root=self.root/allele_key(variant);root.mkdir(parents=True,exist_ok=True)
        descriptor,temporary=tempfile.mkstemp(prefix='.'+provider+'-',suffix='.json',dir=root)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,root/(provider+'.json'))
        finally:Path(temporary).unlink(missing_ok=True)

    def load(self,variant):
        identity=canonical_identity(variant);root=self.root/allele_key(variant);results=[]
        def local_picture(path):
            try:
                path=Path(path).resolve()
                return path.is_relative_to(root.resolve()) and path.suffix.lower()=='.png' and path.is_file()
            except (OSError,TypeError,ValueError):return False
        for provider in PROVIDERS:
            path=root/(provider+'.json')
            try:
                if path.stat().st_size>2_000_000:continue
                data=json.loads(path.read_text(encoding='utf-8'))
                if data.get('provider')!=provider or data.get('status') not in STATUSES:continue
                if canonical_identity(data.get('identity') or {})!=identity:continue
                data={k:v for k,v in data.items() if k in FIELDS}
                if not local_picture(data.get('screenshot')):data.pop('screenshot',None)
                data['screenshots']=[r for r in data.get('screenshots',[]) if isinstance(r,dict) and local_picture(r.get('path'))]
                results.append(data)
            except (OSError,ValueError,TypeError,AttributeError):continue
        return results
