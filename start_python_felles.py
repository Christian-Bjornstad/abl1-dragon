"""Paste-compatible Python FELLES startup, without a child Python process."""
from pathlib import Path
import runpy

def main():
    root=Path(__file__).resolve().parent
    return runpy.run_path(str(root/'packaging/felles.py'),run_name='abl1_felles_helpers')['entry']('start',root)

if __name__=='__main__':raise SystemExit(main())
