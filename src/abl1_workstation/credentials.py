"""App-scoped accounts in Windows Credential Manager; no plaintext fallback.

Win32 contract: learn.microsoft.com/windows/win32/api/wincred/
"""
import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path
import sys

PROVIDERS=('franklin','oncokb','mtbp')

class CredentialStoreError(RuntimeError):pass

class _Credential(ctypes.Structure):
    _fields_=[('Flags',wintypes.DWORD),('Type',wintypes.DWORD),('TargetName',wintypes.LPWSTR),
              ('Comment',wintypes.LPWSTR),('LastWritten',wintypes.FILETIME),
              ('CredentialBlobSize',wintypes.DWORD),('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),
              ('Persist',wintypes.DWORD),('AttributeCount',wintypes.DWORD),('Attributes',ctypes.c_void_p),
              ('TargetAlias',wintypes.LPWSTR),('UserName',wintypes.LPWSTR)]

class WindowsVault:
    def __init__(self):
        if sys.platform!='win32':raise CredentialStoreError('Lagret innlogging krever Windows passordlager.')
        self.api=ctypes.WinDLL('Advapi32.dll',use_last_error=True)
        self.api.CredReadW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.POINTER(_Credential))]
        self.api.CredReadW.restype=wintypes.BOOL
        self.api.CredWriteW.argtypes=[ctypes.POINTER(_Credential),wintypes.DWORD];self.api.CredWriteW.restype=wintypes.BOOL
        self.api.CredDeleteW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD];self.api.CredDeleteW.restype=wintypes.BOOL
        self.api.CredFree.argtypes=[ctypes.c_void_p];self.api.CredFree.restype=None
    def read(self,target):
        pointer=ctypes.POINTER(_Credential)()
        if not self.api.CredReadW(target,1,0,ctypes.byref(pointer)):
            if ctypes.get_last_error()==1168:return '',''
            raise CredentialStoreError('Windows kunne ikke lese lagret innlogging.')
        try:
            value=pointer.contents
            if value.CredentialBlobSize>2560 or value.CredentialBlobSize%2:raise CredentialStoreError('Ugyldig lagret innlogging.')
            return value.UserName or '',ctypes.string_at(value.CredentialBlob,value.CredentialBlobSize).decode('utf-16-le')
        finally:self.api.CredFree(pointer)
    def write(self,target,email,password):
        raw=password.encode('utf-16-le');buffer=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
        value=_Credential();value.Type=1;value.TargetName=target;value.UserName=email
        value.CredentialBlobSize=len(raw);value.CredentialBlob=buffer;value.Persist=2
        try:
            if not self.api.CredWriteW(ctypes.byref(value),0):raise CredentialStoreError('Windows kunne ikke lagre innloggingen.')
        finally:ctypes.memset(buffer,0,len(raw))
    def delete(self,target):
        if not self.api.CredDeleteW(target,1,0) and ctypes.get_last_error()!=1168:
            raise CredentialStoreError('Windows kunne ikke fjerne innloggingen.')

class CredentialStore:
    def __init__(self,folder,*,backend=None):
        self.scope=hashlib.sha256(str(Path(folder).resolve()).casefold().encode()).hexdigest()[:24]
        self.backend=backend
    def _vault(self):
        if self.backend is None:self.backend=WindowsVault()
        return self.backend
    def _key(self,provider):
        if provider not in PROVIDERS:raise ValueError('Ukjent innloggingskilde.')
        return 'DRAGEN/'+self.scope+'/'+provider
    def get(self,provider):return self._vault().read(self._key(provider))
    def save(self,provider,email,password):
        key=self._key(provider);email=email.strip()
        if not email or not password or len(email)>320 or len(password.encode('utf-16-le'))>2560 or any(ord(c)<32 for c in email):
            raise ValueError('Fyll inn e-post og passord.')
        self._vault().write(key,email,password)
    def delete(self,provider):self._vault().delete(self._key(provider))
