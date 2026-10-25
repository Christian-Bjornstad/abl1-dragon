"""Manual Edge handoff. Never reads credentials, cookies, or database pages."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import quote, urlsplit, urlunsplit

ALLOWED_HOSTS = frozenset({
    'www.ncbi.nlm.nih.gov', 'pubmed.ncbi.nlm.nih.gov', 'franklin.genoox.com',
    'www.oncokb.org', 'cancer.sanger.ac.uk', 'grch37-cancer.sanger.ac.uk', 'mtbp.org',
    'gnomad.broadinstitute.org', 'civicdb.org', 'www.uniprot.org',
    'reg.clinicalgenome.org', 'clinicalgenome.org', 'www.clinicalgenome.org',
    'omim.org', 'www.omim.org',
})


def checked_url(url):
    if not isinstance(url, str) or any(ord(c)<32 or ord(c)==127 for c in url) or '\\' in url:
        raise ValueError('Ugyldig databaseadresse.')
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname not in ALLOWED_HOSTS
            or parts.username is not None or parts.password is not None
            or parts.netloc != parts.hostname or '%' in parts.netloc):
        raise ValueError('Bruk en kjent HTTPS-databaseadresse uten brukerinformasjon eller port.')
    # Preserve existing URL escapes; encode Unicode rather than invoking a shell.
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe='/%:@-._~'),
                       quote(parts.query, safe='=&%:+,;/?@-._~'), quote(parts.fragment, safe='%/-._~')))


def profile_policy():
    """Mandatory Edge policy overrides --user-data-dir; fail closed if unreadable."""
    if sys.platform != 'win32': return {'configured': False, 'error': None}
    import winreg
    try:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(root, r'Software\Policies\Microsoft\Edge', 0, winreg.KEY_READ | view) as key:
                        try: value, _ = winreg.QueryValueEx(key, 'UserDataDir')
                        except FileNotFoundError: continue
                        if value: return {'configured': True, 'error': None}
                except FileNotFoundError: continue
        return {'configured': False, 'error': None}
    except OSError as error:
        return {'configured': False, 'error': str(error)}


class EdgeBrowser:
    def __init__(self, data_dir, executable=None):
        self.data_dir = Path(data_dir).resolve()
        self.profile_dir = self.data_dir/'EdgeProfil'
        self.settings = self.data_dir/'edge-settings.json'
        self.config_error = None
        self._executable = self._validated_executable(executable) if executable else None
        if executable is None and self.settings.exists():
            try:
                if self.settings.stat().st_size>8192: raise ValueError('Edge-innstilling er for stor.')
                config = json.loads(self.settings.read_text(encoding='utf-8'))
                self._executable = self._validated_executable(Path(config['executable']))
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.config_error = str(error)

    @staticmethod
    def _validated_executable(path):
        path = Path(path).resolve()
        if path.name.lower() != 'msedge.exe' or not path.is_file():
            raise ValueError('Velg en eksisterende msedge.exe fra Microsoft Edge-installasjonen.')
        return path

    def executable_path(self):
        if self._executable:
            return self._executable if self._executable.is_file() else None
        if self.config_error: return None
        for name in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
            folder = os.environ.get(name)
            if folder:
                path = Path(folder)/'Microsoft/Edge/Application/msedge.exe'
                if path.is_file(): return path.resolve()
        return None

    def set_executable(self, path):
        selected = self._validated_executable(path)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.data_dir, prefix='.edge-', suffix='.json')
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump({'executable': str(selected)}, stream)
            os.replace(temporary, self.settings)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self._executable = selected
        self.config_error = None
        return selected

    def diagnostics(self):
        executable = self.executable_path()
        policy = profile_policy()
        warning = ('Edge-policy overstyrer profilvalget. Avklar egen profil med IT.' if policy['configured'] else
                   'Edge-policy kunne ikke kontrolleres. Avklar med IT.' if policy['error'] else None)
        return {'edge_found': bool(executable), 'executable': str(executable) if executable else None,
                'profile_dir': str(self.profile_dir), 'profile_exists': self.profile_dir.is_dir(),
                'authenticated': None, 'config_error': self.config_error,
                'policy_configured': policy['configured'], 'policy_error': policy['error'], 'warning': warning}

    def open_url(self, url):
        url = checked_url(url)
        diagnostics = self.diagnostics()
        if diagnostics['warning']: raise RuntimeError(diagnostics['warning'])
        executable = self.executable_path()
        if executable is None: raise FileNotFoundError('Microsoft Edge er ikke funnet. Velg Edge.exe.')
        if self.profile_dir.resolve()!=self.profile_dir:
            raise RuntimeError('Profilmappen peker til en annen mappe. Velg en egen lokal arbeidsmappe.')
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        return subprocess.Popen([str(executable), '--user-data-dir='+str(self.profile_dir),
                                 '--profile-directory=Default', '--no-first-run', '--new-window', url],
                                shell=False, close_fds=True)
