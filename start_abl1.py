"""Run the source checkout; frozen builds use this same entry point."""
from pathlib import Path
import sys

if not getattr(sys,'frozen',False):sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
if __name__=='__main__':
    try:
        from abl1_workstation.__main__ import main
        exit_code=main()
    except Exception:
        if '--smoke-test' not in sys.argv:raise
        import traceback
        output=Path(sys.argv[sys.argv.index('--smoke-test')+1])
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(traceback.format_exc(),encoding='utf-8')
        exit_code=2
    raise SystemExit(exit_code)
