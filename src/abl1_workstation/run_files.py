"""Deterministic file discovery within one selected local sequencing run."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
from pathlib import Path


@dataclass(frozen=True)
class AlignmentFiles:
    sample: str
    path: Path
    index: Path
    kind: str


@dataclass
class RunFiles:
    vcfs: list[Path]
    alignments: dict[str,AlignmentFiles]=field(default_factory=dict)
    reference_fasta: Path|None=None
    warnings: list[str]=field(default_factory=list)


def _digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _inside_files(folder):
    return sorted({p.resolve() for p in folder.rglob('*') if p.is_file() and p.resolve().is_relative_to(folder)},key=lambda p:p.relative_to(folder).as_posix().casefold())


def _reference(files,folder,warnings,reference):
    candidates=[]
    for path in files:
        if path.suffix.lower() not in ('.fa','.fasta','.fna'):continue
        index=path.with_name(path.name+'.fai')
        if index not in files:
            warnings.append('FASTA mangler lokal .fai: '+path.relative_to(folder).as_posix());continue
        try:
            with index.open(encoding='utf-8-sig') as stream:rows=[line.rstrip('\n').split('\t') for line in stream if line.strip()]
            target=[row for row in rows if row[0] in ('chr9','9')]
            if len(target)!=1 or len(target[0])<5 or int(target[0][1])!=reference['chrom_length']:
                warnings.append('FASTA har ikke forventet hg19 chr9-lengde: '+path.relative_to(folder).as_posix());continue
        except (OSError,ValueError,IndexError):
            warnings.append('FASTA-indeks kunne ikke leses: '+path.relative_to(folder).as_posix());continue
        candidates.append(path)
    if len(candidates)>1:raise ValueError('Flere mulige FASTA-referanser i valgt mappe. Behold/velg én referanse.')
    if candidates:
        warnings.append('FASTA funnet; sekvensens MD5 må kontrolleres ved lesningsanalyse.')
        return candidates[0]
    return None


def discover_run(folder:Path)->RunFiles:
    from .domain import _engine
    folder=Path(folder).resolve()
    if not folder.is_dir():raise ValueError('Velg en lokal kjøringsmappe.')
    engine=_engine();vcfs,warnings=engine.select_vcf_paths(folder)
    files=_inside_files(folder);alignments={}
    aliases={}
    for path in vcfs:
        for sample in engine.vcf_samples(engine.read_vcf_text(path),path.name):
            aliases.setdefault(sample,set()).update((sample,engine.vcf_sample_fallback(path.name)))
    samples=set(aliases)
    matched_paths={}
    for sample in sorted(samples,key=str.casefold):
        accepted={alias+suffix for alias in aliases[sample] for suffix in ('.bam','_tumor.bam','.cram','_tumor.cram')}
        matches=[p for p in files if p.name in accepted]
        if len(matches)>1:raise ValueError('Flere BAM/CRAM-filer for '+sample+'. Velg én entydig alignment.')
        if not matches:
            warnings.append('Ingen BAM/CRAM funnet for '+sample+'.');continue
        path=matches[0];kind=path.suffix.lower().lstrip('.')
        if path in matched_paths:raise ValueError('Samme BAM/CRAM matcher flere VCF-prøver: '+sample+' og '+matched_paths[path]+'.')
        matched_paths[path]=sample
        index_names={path.with_name(path.name+('.bai' if kind=='bam' else '.crai')),path.with_suffix('.bai' if kind=='bam' else '.crai')}
        indexes=sorted((p for p in files if p in index_names),key=lambda p:p.name)
        if not indexes:
            warnings.append('BAM/CRAM mangler indeks for '+sample+'.');continue
        if len(indexes)>1 and len({_digest(index) for index in indexes})>1:
            raise ValueError('Motstridende alignment-indekser for '+sample+'.')
        preferred=path.with_name(path.name+('.bai' if kind=='bam' else '.crai'))
        index=preferred if preferred in indexes else indexes[0]
        alignments[sample]=AlignmentFiles(sample,path,index,kind)
        warnings.append('BAM/CRAM for '+sample+' er funnet på filnavn; prøveidentiteten i headeren må kontrolleres før visning.')
    reference_fasta=_reference(files,folder,warnings,engine.REFERENCE)
    if alignments and reference_fasta is None:warnings.append('Ingen entydig lokal hg19 FASTA med .fai; CRAM-visning/lesningsanalyse krever referanse.')
    return RunFiles(vcfs,alignments,reference_fasta,warnings)
