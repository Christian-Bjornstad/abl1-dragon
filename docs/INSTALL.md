# Windows

Python 3.12–3.14, 64 bit, må være installert. Pakk ut hele offline-pakken
til en fast, skrivbar programmappe.

1. Kjør **Installer ABL1.cmd** én gang.
2. Kjør **Start ABL1.cmd**.

Installeringen lager et isolert `.venv` i programmappen. Med `wheelhouse` til
stede brukes bare lokale pakker. Vanlig oppstart installerer ingenting.
**Kontroller ABL1.cmd** viser Python, avhengigheter og eventuelle feil.
Logg: `work/launcher-logs/bootstrap.log`.

Bestemt Python kan velges med `ABL1_PYTHON` eller første argument:

```cmd
"Installer ABL1.cmd" --python "C:\Python314\python.exe" --offline
"Start ABL1.cmd" --data-dir "D:\LokaleAnalyser\ABL1"
```

## Fra kildekoden

Git-repoet inneholder ingen binære avhengigheter. Bruk **Installer ABL1.cmd --online**
på en PC som kan laste ned Python-pakker, eller lag en wheelhouse for målmaskinen:

```cmd
python -m pip download --only-binary=:all: -r requirements-desktop.txt --dest wheelhouse
```

Ved flytting til en annen Python-versjon trengs kompatible wheels, særlig PyQt6-sip.
Den ferdige offline-pakken inkluderer Windows x64-wheels for 3.12, 3.13 og 3.14.
Ikke flytt et ferdig `.venv` mellom maskiner.

## Python FELLES / Ivanti

Angi lokalt godkjent program-ID i `ABL1_IVANTI_APP_ID`. `ABL1_IVANTI` kan overstyre
banen til `pwrgate.exe`. Kjør **Installer med Python FELLES.cmd**, lim inn den
kopierte kommandoen i Python-vinduet og trykk Enter. Etter installasjon lukkes
vinduet. Bruk deretter **Start med Python FELLES.cmd** på samme måte.

FELLES-flyten bruker samme interpreter og appens `.felles-packages`, uten å endre
globale pakker. Den krever wheelhouse, pip og et nytt FELLES-vindu uten innlastet Qt.
Ivanti- og organisasjonspolicy må kontrolleres lokalt.

## Edge

Velg kilde under **Kilder og databaser**, og bruk **Åpne / logg inn i Edge**.
Fullfør innlogging og MFA i Edge. **Kopier søketekst** gir allel, referansebygg
og transkript for manuelle søk. Nettleserinnlogging aktiverer ingen kilde-API.

Appen ber om egen profil under arbeidsmappens `EdgeProfil`. Den stopper hvis
påvist Edge-policy overstyrer profilvalget, eller policykontrollen ikke kan leses.
Ingen passord eller cookies leses. Profilen skal ikke deles eller legges i Git.
