"""Install DRAGEN offline inside the active Python FELLES interpreter."""
from pathlib import Path
import runpy

def main():
    root=Path(__file__).resolve().parent
    helpers=runpy.run_path(str(root/'packaging/felles.py'),run_name='dragen_install_helpers')
    return helpers['entry']('install',root)

if __name__=='__main__':raise SystemExit(main())
