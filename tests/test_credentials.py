import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from abl1_workstation.credentials import CredentialStore

class MemoryVault:
    def __init__(self):self.rows={}
    def read(self,key):return self.rows.get(key,('',''))
    def write(self,key,email,password):self.rows[key]=(email,password)
    def delete(self,key):self.rows.pop(key,None)

class CredentialTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Windows Credential Manager')
    def test_windows_vault_round_trip_and_delete_use_only_a_unique_synthetic_account(self):
        with tempfile.TemporaryDirectory(prefix='dragen-credential-test-') as directory:
            store=CredentialStore(directory)
            try:
                store.save('franklin','synthetic@example.invalid','SYNTHETIC_ONLY_åøæ')
                self.assertEqual(CredentialStore(directory).get('franklin'),('synthetic@example.invalid','SYNTHETIC_ONLY_åøæ'))
            finally:store.delete('franklin')
            self.assertEqual(store.get('franklin'),('',''))
    def test_saved_accounts_are_separate_and_never_written_to_project_files(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=MemoryVault();store=CredentialStore(directory,backend=backend)
            store.save('franklin','synthetic@example.invalid','NOT_A_REAL_PASSWORD')
            store.save('oncokb','other@example.invalid','OTHER_TEST_PASSWORD')
            again=CredentialStore(directory,backend=backend)
            self.assertEqual(again.get('franklin'),('synthetic@example.invalid','NOT_A_REAL_PASSWORD'))
            self.assertEqual(len(list(Path(directory).iterdir())),0)
            self.assertEqual(CredentialStore(directory+'-other',backend=backend).get('franklin'),('',''))
            store.delete('franklin');self.assertEqual(store.get('franklin'),('',''))
            self.assertTrue(store.get('oncokb')[1])
    def test_unknown_provider_and_incomplete_account_are_rejected(self):
        store=CredentialStore('.',backend=MemoryVault())
        with self.assertRaises(ValueError):store.save('attacker','x','password')
        with self.assertRaises(ValueError):store.save('franklin','x','')

if __name__=='__main__':unittest.main()
