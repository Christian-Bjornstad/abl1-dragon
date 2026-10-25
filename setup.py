"""Include local evidence assets in installed wheels as well as source/EXE builds."""
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py

ROOT=Path(__file__).resolve().parent
RESOURCE_ITEMS=('assets/brand','assets/igv','desktop/data/pilot.json','engine/analyze.py','engine/reference.json',
                'engine/read_evidence.py','engine/requirements-read-evidence.txt',
                'app/data/knowledge.json','app/data/igv-manifest.json')


class BuildWithResources(build_py):
    def run(self):
        super().run()
        destination=Path(self.build_lib)/'abl1_workstation/resources'
        for relative in RESOURCE_ITEMS:
            source=ROOT/relative;target=destination/relative
            if source.is_dir():
                shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            else:
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)


setup(cmdclass={'build_py':BuildWithResources})
