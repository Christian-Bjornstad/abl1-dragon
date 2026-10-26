"""Build public hg19 annotation tracks from the bundled RefSeq map and UCSC."""
import gzip,json
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]

def build():
    reference=json.loads((ROOT/'engine/reference.json').read_text(encoding='utf-8'))
    folder=ROOT/'assets/igv';exons=reference['exons'];start=exons[0]['start0'];end=exons[-1]['end0']
    coding={int(position)-1:index for position,index in reference['coding_map'].items()}
    fields=['chr9',start,end,'ABL1 · NM_005157.6',0,'+',min(coding),max(coding)+1,'65,45,115',len(exons),
            ','.join(str(e['end0']-e['start0']) for e in exons),','.join(str(e['start0']-start) for e in exons)]
    (folder/'abl1.bed').write_text('\t'.join(map(str,fields))+'\n',encoding='utf-8')
    codons=[a+b+c for a in 'TCAG' for b in 'TCAG' for c in 'TCAG']
    amino=dict(zip(codons,'FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG'))
    inverse={value:position for position,value in coding.items()};sequence=reference['transcript_sequence'][reference['cds_start_t0']:]
    rows=[]
    for index in range(1,max(inverse)-1,3):
        positions=[inverse[index+i] for i in range(3)]
        # Split-exon codons cannot be drawn as one contiguous three-base block.
        if positions!=list(range(positions[0],positions[0]+3)):continue
        aa=amino.get(sequence[index-1:index+2],'X');position=positions[0]
        rows.append('\t'.join(map(str,['chr9',position,position+3,aa,0,'+',position,position+3,'65,45,115' if index%6==1 else '105,85,155'])))
    (folder/'protein.bed').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    with urlopen('https://hgdownload.soe.ucsc.edu/goldenPath/hg19/database/cytoBand.txt.gz',timeout=30) as response:
        data=gzip.decompress(response.read(2_000_000)).decode()
    lines=[line for line in data.splitlines() if line.startswith('chr9\t')]
    if not lines or int(lines[-1].split('\t')[2])!=141213431:raise ValueError('Uventet hg19-karyotype.')
    (folder/'cytoband.txt').write_text('\n'.join(lines)+'\n',encoding='ascii')
    print('Built hg19 chr9 cytobands, NM_005157.6 and',len(rows),'protein codons.')

if __name__=='__main__':build()
