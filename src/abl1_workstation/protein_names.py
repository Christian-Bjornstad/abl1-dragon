"""Protein display names; internal variant and database identities stay unchanged."""
import re

AA3=dict(zip('ACDEFGHIKLMNPQRSTVWY*',
            ('Ala','Cys','Asp','Glu','Phe','Gly','His','Ile','Lys','Leu','Met',
             'Asn','Pro','Gln','Arg','Ser','Thr','Val','Trp','Tyr','Ter')))
AA1={value:key for key,value in AA3.items()}


def protein_key(value):
    """Normalize one substitution only, never a compound or uncertain effect."""
    text=str(value or '').strip().removeprefix('p.')
    match=re.fullmatch(r'([ACDEFGHIKLMNPQRSTVWY]|[A-Z][a-z]{2})([1-9][0-9]*)([ACDEFGHIKLMNPQRSTVWY*]|[A-Z][a-z]{2}|=)',text)
    if not match:return None
    ref,pos,alt=match.groups();ref=AA1.get(ref,ref);alt=AA1.get(alt,alt)
    if ref=='*' or ref not in AA3 or alt not in (*AA3,'='):return None
    return ref+pos+alt


def protein_display(value):
    text=str(value or '')
    # Tokenize residue+position and substitution suffix independently so del,
    # dup, fs and uncertain HGVS punctuation are retained, not reinterpreted.
    text=re.sub(r'(?<![A-Za-z])([ACDEFGHIKLMNPQRSTVWY])(?=[1-9][0-9]*)',lambda m:AA3[m[1]],text)
    return re.sub(r'(?<=[0-9])([ACDEFGHIKLMNPQRSTVWY*])(?=$|[);_\[\]]|fs|del|dup|ins)',lambda m:AA3[m[1]],text)
