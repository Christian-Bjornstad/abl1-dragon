"""Offline app-local packages in the running Python FELLES interpreter."""
from pathlib import Path
import runpy

def main():
    root=Path(__file__).resolve().parent
    return runpy.run_path(str(root/'packaging/felles.py'),run_name='abl1_felles_helpers')['entry']('install',root)

if __name__=='__main__':raise SystemExit(main())
