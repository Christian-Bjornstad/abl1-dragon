"""Bundle committed source and local Windows wheels. Does not download anything."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tomllib
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def build(wheelhouse, output):
    wheels=sorted(Path(wheelhouse).glob('*.whl'))
    if not wheels:raise ValueError('Wheelhouse mangler Windows-avhengigheter.')
    for arguments in (['diff','--quiet'],['diff','--cached','--quiet']):
        subprocess.run(['git','-C',str(ROOT),*arguments],check=True)
    archive=subprocess.run(['git','-C',str(ROOT),'archive','--format=zip','HEAD'],capture_output=True,check=True).stdout
    revision=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    checksums={}
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as package:
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            for name in source.namelist():
                if name.endswith('/'):continue
                if '..' in Path(name).parts:raise ValueError('Ugyldig Git-filbane.')
                raw=source.read(name);checksums[name]=hashlib.sha256(raw).hexdigest()
                package.writestr('ABL1_Dragon/'+name,raw)
        for wheel in wheels:
            name='wheelhouse/'+wheel.name
            with wheel.open('rb') as stream:checksums[name]=hashlib.file_digest(stream,'sha256').hexdigest()
            package.write(wheel,'ABL1_Dragon/'+name,compress_type=zipfile.ZIP_STORED)
        manifest={'version':version,'commit':revision,'sha256':checksums}
        package.writestr('ABL1_Dragon/SHA256SUMS.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(output) as package:
        if package.testzip():raise ValueError('ZIP CRC-feil.')
        for name,checksum in checksums.items():
            if hashlib.sha256(package.read('ABL1_Dragon/'+name)).hexdigest()!=checksum:
                raise ValueError('Hash-avvik: '+name)
    with output.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    receipt={'file':output.name,'version':version,'commit':revision,'sha256':checksum,
             'bytes':output.stat().st_size,'member_hashes_verified':True,'source':'committed public repository'}
    output.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheelhouse',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/ABL1_Dragon_Python_offline.zip')
    args=parser.parse_args();build(args.wheelhouse,args.output)
