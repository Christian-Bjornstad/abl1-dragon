"""Prepare the bundled public hg19 chr9 FASTA and FAI without network access."""
import gzip,hashlib,json,os,tempfile
from pathlib import Path

MAX_FASTA_BYTES=160_000_000

def _digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def prepare_reference(bundle,destination):
    bundle=Path(bundle);destination=Path(destination)
    metadata=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    size=metadata.get('fasta_bytes')
    if metadata.get('assembly')!='GRCh37' or metadata.get('chromosome')!='chr9' or type(size) is not int or not 0<size<=MAX_FASTA_BYTES:
        raise ValueError('Ugyldig medfølgende hg19-referanse.')
    archive=bundle/'chr9.fa.gz';source_index=bundle/'chr9.fa.fai'
    if source_index.stat().st_size>1024 or _digest(source_index)!=metadata['index_sha256']:
        raise ValueError('Den medfølgende referanseindeksen har feil kontrollsum.')
    index_bytes=source_index.read_bytes();fields=index_bytes.decode('ascii').strip().split('\t')
    if len(fields)!=5 or fields[0]!='chr9' or int(fields[1])!=metadata['length']:
        raise ValueError('Den medfølgende referanseindeksen har feil kromosom/lengde.')
    fasta=destination/'chr9.fa';index=destination/'chr9.fa.fai'
    if fasta.is_file() and fasta.stat().st_size==size and _digest(fasta)==metadata['fasta_sha256']:
        if index.is_file() and _digest(index)==metadata['index_sha256']:return fasta
    if _digest(archive)!=metadata['gzip_sha256']:raise ValueError('Den medfølgende hg19-arkivfilen har feil kontrollsum.')
    destination.mkdir(parents=True,exist_ok=True)
    temporary=[]
    try:
        descriptor,name=tempfile.mkstemp(prefix='.chr9-',suffix='.tmp',dir=destination);temporary.append(Path(name))
        digest=hashlib.sha256();observed=0
        with os.fdopen(descriptor,'wb') as output,gzip.open(archive,'rb') as source:
            while chunk:=source.read(1024*1024):
                observed+=len(chunk)
                if observed>size:raise ValueError('Medfølgende FASTA er større enn oppgitt.')
                output.write(chunk);digest.update(chunk)
        if observed!=size or digest.hexdigest()!=metadata['fasta_sha256']:
            raise ValueError('Medfølgende FASTA er avkortet eller har feil kontrollsum.')
        descriptor,index_name=tempfile.mkstemp(prefix='.chr9-index-',suffix='.tmp',dir=destination);temporary.append(Path(index_name))
        with os.fdopen(descriptor,'wb') as output:output.write(index_bytes)
        os.replace(index_name,index);os.replace(name,fasta)
        return fasta
    except (EOFError,gzip.BadGzipFile) as error:raise ValueError('Medfølgende hg19-arkiv kunne ikke pakkes ut.') from error
    finally:
        for path in temporary:path.unlink(missing_ok=True)

def bundled_reference(root,state_folder=None):
    """Prefer the managed program cache; use app data if program files are read-only."""
    root=Path(root);bundle=root/'assets/reference'
    if not (bundle/'manifest.json').is_file():return None
    try:return prepare_reference(bundle,root/'reference/hg19')
    except PermissionError:
        if state_folder is None:raise
        return prepare_reference(bundle,Path(state_folder)/'reference/hg19')
