"""Local-only ABL1 source bootstrap. Standard library; start/check never install."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import venv

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.+!-]*)")
RESOURCE_FILES = ("engine/analyze.py", "desktop/data/pilot.json",
                  "app/data/knowledge.json", "app/data/igv-manifest.json")


def environment_python(root):
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def child_environment():
    result = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE",
                "PIP_TARGET", "PIP_PREFIX", "PIP_USER"):
        result.pop(key, None)
    result["PYTHONIOENCODING"] = "utf-8"
    return result


def python_supported(spec, version):
    """The release uses comma-separated explicit numeric Requires-Python bounds."""
    actual = tuple(version[:3])
    for part in spec.split(","):
        match = re.fullmatch(r"\s*(>=|<=|==|!=|>|<)\s*(\d+)\.(\d+)(?:\.(\d+))?\s*", part)
        if match is None:
            raise ValueError("Ukjent Requires-Python-format: " + spec)
        operator, major, minor, patch = match.groups()
        expected = (int(major), int(minor), int(patch or 0))
        accepted = {">=": actual >= expected, "<=": actual <= expected,
                    ">": actual > expected, "<": actual < expected,
                    "==": actual == expected, "!=": actual != expected}[operator]
        if not accepted:
            return False
    return True


def project_metadata(root):
    try:
        import tomllib
    except ImportError as error:
        raise RuntimeError("Velg en støttet Python 3.12–3.14 med --python eller ABL1_PYTHON.") from error
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    spec = project["requires-python"]
    if not python_supported(spec, sys.version_info):
        raise RuntimeError(f"Python {sys.version.split()[0]} støttes ikke; prosjektet krever {spec}.")
    for name in ("requirements-desktop.txt", "start_abl1.py"):
        if not (root / name).is_file():
            raise RuntimeError(f"Den komplette kildekodemappen mangler {name}.")
    if not (root / "src/abl1_workstation").is_dir():
        raise RuntimeError("Den komplette kildekodemappen mangler src/abl1_workstation.")
    return project


def pinned_requirements(root):
    result = []
    for number, line in enumerate((root / "requirements-desktop.txt").read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if match is None:
            raise ValueError(f"requirements-desktop.txt:{number}: forventer eksplisitt pakke==versjon.")
        result.append({"name": match[1], "required": match[2]})
    return result


def probe_environment(python, requirements):
    code = """import importlib.metadata as m,json,sys
rows=json.loads(sys.argv[1])
for row in rows:
    try: row['installed']=m.version(row['name'])
    except m.PackageNotFoundError: row['installed']=None
print(json.dumps({'version':list(sys.version_info[:3]),'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,'requirements':rows}))
"""
    completed = subprocess.run([str(python), "-I", "-c", code, json.dumps(requirements)],
                               capture_output=True, encoding="utf-8", errors="replace",
                               env=child_environment(), timeout=45)
    if completed.returncode:
        raise RuntimeError("Kunne ikke kontrollere .venv: " + completed.stderr.strip())
    return json.loads(completed.stdout)


def diagnostic(root, project, requirements):
    python = environment_python(root)
    result = {"project": str(root), "application_version": project["version"],
              "requires_python": project["requires-python"], "bootstrap_python": sys.executable,
              "environment_python": str(python), "requirements": requirements,
              "ready": False, "errors": []}
    if (root / ".abl1-install.lock").exists():
        result["errors"].append("Installasjon pågår; vent til Installer ABL1.cmd er ferdig.")
    if not python.is_file():
        result["errors"].append("Lokalt .venv mangler. Kjør Installer ABL1.cmd først.")
        return result
    try:
        cfg = (root / ".venv/pyvenv.cfg").read_text(encoding="utf-8").lower()
        if re.search(r"include-system-site-packages\s*=\s*true", cfg):
            raise RuntimeError(".venv bruker globale pakker; bruk et isolert miljø.")
        details = probe_environment(python, requirements)
        result.update(details)
        if details["prefix"] == details["base_prefix"]:
            result["errors"].append("Valgt .venv-python er ikke et isolert virtualenv.")
        if not python_supported(project["requires-python"], details["version"]):
            result["errors"].append("Eksisterende .venv har feil Python-versjon. Bevar eller flytt det før ny installasjon.")
        for row in details["requirements"]:
            if row["installed"] != row["required"]:
                result["errors"].append(f"{row['name']}: krever {row['required']}, funnet {row['installed'] or 'mangler'}. Kjør Installer ABL1.cmd.")
        for relative in RESOURCE_FILES:
            if not (root / relative).is_file():
                result["errors"].append("Ressurs mangler: " + relative)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        result["errors"].append(str(error))
    result["ready"] = not result["errors"]
    return result


def log_path(root):
    for folder in (root / "work/launcher-logs", Path(tempfile.gettempdir()) / "ABL1-Tolkning/logs"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "bootstrap.log"
            with path.open("a", encoding="utf-8"):
                pass
            return path
        except OSError:
            continue
    return None


def record(path, message):
    if path is not None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")


def run_logged(command, root, logfile):
    """Preserve console stdout/stderr and append both streams to the local log."""
    record(logfile, "subprocess=" + str(command[0]))
    process = subprocess.Popen(command, cwd=root, env=child_environment(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", bufsize=1)
    lock = threading.Lock()
    def forward(source, target, channel):
        try:
            for line in iter(source.readline, ""):
                target.write(line)
                target.flush()
                with lock:
                    record(logfile, channel + ": " + line.rstrip("\n"))
        finally:
            source.close()
    workers = [threading.Thread(target=forward, args=(process.stdout, sys.stdout, "stdout")),
               threading.Thread(target=forward, args=(process.stderr, sys.stderr, "stderr"))]
    for worker in workers:
        worker.start()
    code = process.wait()
    for worker in workers:
        worker.join()
    record(logfile, f"exit_code={code}")
    return code


@contextmanager
def installation_lock(root):
    path = root / ".abl1-install.lock"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as error:
        raise RuntimeError("En installasjon pågår eller ble avbrutt. Kontroller .abl1-install.lock før nytt forsøk.") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def install(root, args, project, logfile):
    wheelhouse = Path(args.wheelhouse).resolve() if args.wheelhouse else root / "wheelhouse"
    offline = args.offline or bool(args.wheelhouse) or (wheelhouse.is_dir() and not args.online)
    if args.online:
        offline = False
    if offline and not wheelhouse.is_dir():
        raise RuntimeError("Offline installasjon krever en lokal wheelhouse-mappe; ingen online reserve brukes.")
    with installation_lock(root):
        python = environment_python(root)
        if python.is_file():
            details = probe_environment(python, [])
            if not python_supported(project["requires-python"], details["version"]):
                raise RuntimeError("Eksisterende .venv har feil Python-versjon. Bevar eller flytt det før ny installasjon.")
        else:
            print("Oppretter isolert miljø i " + str(root / ".venv"), flush=True)
            venv.EnvBuilder(with_pip=True, system_site_packages=False).create(root / ".venv")
        command = [str(python), "-I", "-m", "pip", "--isolated", "install",
                   "--require-virtualenv", "--no-user", "--no-input",
                   "--disable-pip-version-check", "--only-binary=:all:"]
        if offline:
            command += ["--no-index", "--find-links", str(wheelhouse)]
        command += ["-r", str(root / "requirements-desktop.txt")]
        print("Installerer låste avhengigheter " + ("offline fra " + str(wheelhouse) if offline else "fra pakkeindeks (nettverk)."), flush=True)
        result = run_logged(command, root, logfile)
        if result:
            return result
    checked = diagnostic(root, project, pinned_requirements(root))
    if not checked["ready"]:
        raise RuntimeError("\n".join(checked["errors"]))
    print("Installasjonen er kontrollert. Bruk Start ABL1.cmd.", flush=True)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "install", "check"), nargs="?", default="start")
    parser.add_argument("--python", help="Full sti til ønsket bootstrap-/installasjons-Python")
    parser.add_argument("--check", action="store_true", help="Diagnostikk uten GUI eller installasjon")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--online", action="store_true")
    parser.add_argument("--wheelhouse", type=Path)
    args, app_arguments = parser.parse_known_args(argv)
    if args.check:
        args.action = "check"
    if args.action != "start" and app_arguments:
        parser.error("Ukjente argumenter: " + " ".join(app_arguments))
    root = ROOT.resolve()
    logfile = log_path(root)
    try:
        requested = args.python or os.environ.get("ABL1_PYTHON")
        if requested:
            selected = Path(requested).expanduser().resolve()
            if not selected.is_file():
                raise RuntimeError("Valgt Python finnes ikke: " + str(selected))
            if selected != Path(sys.executable).resolve():
                clean = list(argv)
                if "--python" in clean:
                    index = clean.index("--python")
                    del clean[index:index + 2]
                return run_logged([str(selected), str(Path(__file__).resolve()), *clean], root, logfile)
        project = project_metadata(root)
        requirements = pinned_requirements(root)
        record(logfile, f"action={args.action} project={root} python={sys.executable}")
        if args.action == "install":
            return install(root, args, project, logfile)
        checked = diagnostic(root, project, requirements)
        if args.action == "check":
            print(json.dumps(checked, ensure_ascii=False, indent=2))
            return 0 if checked["ready"] else 1
        if not checked["ready"]:
            raise RuntimeError("\n".join(checked["errors"]))
        return run_logged([str(environment_python(root)), "-I", str(root / "start_abl1.py"), *app_arguments], root, logfile)
    except Exception as error:
        record(logfile, traceback.format_exc())
        print("ABL1 kunne ikke " + ("installeres" if args.action == "install" else "startes/kontrolleres") + ": " + str(error), file=sys.stderr)
        if logfile:
            print("Oppstartslogg: " + str(logfile), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
