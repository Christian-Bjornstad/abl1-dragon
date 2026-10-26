"""Bundle a verified public hg19 chr9 FASTA; no sample data or network."""
import argparse,gzip,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from abl1_workstation.igv_live import inspect_reference,verify_reference

def build(fasta):
    reference=inspect_reference(fasta);md5=verify_reference(reference)
    folder=ROOT/'assets/reference';folder.mkdir(parents=True,exist_ok=True)
    archive=folder/'chr9.fa.gz';index=folder/'chr9.fa.fai'
    with reference.fasta.open('rb') as source,archive.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') as compressed:
        shutil.copyfileobj(source,compressed,1024*1024)
    shutil.copyfile(reference.index,index)
    def sha(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    manifest={'assembly':'GRCh37','chromosome':'chr9','length':reference.length,'sequence_md5':md5,
              'fasta_bytes':reference.fasta.stat().st_size,'fasta_sha256':sha(reference.fasta),'gzip_sha256':sha(archive),'index_sha256':sha(index),
              'source_url':'https://hgdownload.soe.ucsc.edu/goldenPath/hg19/chromosomes/chr9.fa.gz','privacy':'Public reference only; no individual sequence or assay data.'}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'gzip_bytes':archive.stat().st_size,**manifest}))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('fasta',type=Path);build(parser.parse_args().fasta)
