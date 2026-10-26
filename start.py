"""Start DRAGEN inside the active Python FELLES interpreter."""
from pathlib import Path
import runpy

def main(argv=None):
    root=Path(__file__).resolve().parent
    helpers=runpy.run_path(str(root/'packaging/felles.py'),run_name='dragen_start_helpers')
    return helpers['entry']('start',root,argv=argv)

if __name__=='__main__':
    import sys
    raise SystemExit(main(sys.argv[1:]))
