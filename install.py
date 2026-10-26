"""Install DRAGEN in the active interpreter, as with PRONTO."""
from pathlib import Path
import runpy

def main(argv=None):
    root=Path(__file__).resolve().parent
    helpers=runpy.run_path(str(root/'packaging/felles.py'),run_name='dragen_install_helpers')
    return helpers['entry']('install',root,argv=argv)

if __name__=='__main__':
    import sys
    raise SystemExit(main(sys.argv[1:]))
