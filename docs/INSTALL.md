# Installer og start fra GitHub

Last ned hele **main**-branchen og pakk ut til en fast, skrivbar mappe. Ikke kopier bare CMD-filene.

1. Kjør **INSTALL_DRAGEN.cmd**.
2. Lukk Python FELLES når installasjonen er ferdig.
3. Kjør **START_DRAGEN.cmd**.

På jobb-PC åpner CMD-filene Python FELLES gjennom Ivanti, som i PRONTO. Kommandoen
kopieres til utklippstavlen. Lim inn med **Ctrl+V** i FELLES og trykk **Enter**.
Bruk et nytt FELLES-vindu etter installasjon. Ingen release eller `wheelhouse` kreves:
installasjonen henter de låste Python-pakkene når de ikke følger kildekoden.
Dette krever nettverkstilgang til Python-pakkeregisteret.

Installasjonen er ferdig når Python FELLES viser **DRAGEN ER FERDIG INSTALLERT** i en
tydelig ramme. Meldingen vises etter kontroll av pakkeversjonene, også hvis riktig
installasjon allerede finnes. Ved feil vises ingen ferdigmelding.

Hele hg19 chr9-referansen og `.fai` følger kildekoden. Installasjonen pakker FASTA
ut i `reference/hg19`; appen velger den automatisk. Ingen separat nedlasting av
referanse eller IGV.js er nødvendig. Ved første start kontrolleres og eventuelt
repareres den lokale referansekopien fra den medfølgende pakken.

På Windows bruker IGV eksisterende **Microsoft Edge (`msedge.exe`)** i et eget
appstyrt vindu. Referanse og lesninger leveres bare på lokal loopback.
Appen bruker Edge DevTools til å kontrollere lasting og hente IGV-bildet til
Excel. Standardinstallasjonen trenger ikke PyQt6-WebEngine eller en ekstra
`QtWebEngineProcess.exe`. Organisasjonens Edge-policyer respekteres.

## Samme startmønster som PRONTO

De to CMD-filene inneholder hele valget av interpreter. De bruker `install.py` og
`start.py` direkte; ingen ekstra CMD-hjelpefiler må kjedes sammen.

- Ivanti: `C:\Program Files (x86)\Ivanti\Workspace Control\pwrgate.exe`, program-ID **15694**.
- Uten Ivanti: eksplisitt `DRAGEN_PYTHON`, lokal `.venv`, Python Launcher 3.14, deretter `python.exe` på PATH.
- `DRAGEN_IVANTI` kan angi en annen Ivanti-bane. Tidligere `ABL1_IVANTI` og `ABL1_PYTHON` støttes fortsatt.
- En utklippstavlefeil stopper ikke Ivanti; en kommando som kan kopieres manuelt vises.

For å velge lokal Python selv på en PC med Ivanti:

```cmd
set DRAGEN_LOCAL_PYTHON=1
set DRAGEN_PYTHON=C:\Python314\python.exe
INSTALL_DRAGEN.cmd
START_DRAGEN.cmd
```

Tilleggsargumenter gjelder ved lokal start, for eksempel `START_DRAGEN.cmd --data-dir D:\DRAGEN-data`.
En innlimt FELLES-kommando videresender ikke Python-vertens egne argumenter.

## Pakker og reparasjon

Python 3.12–3.14, Windows 64 bit støttes. PRONTO/FELLES-flyten bruker Python 3.14.
Installasjonen kjører pip i samme interpreter, uten en underordnet `python.exe`.
Pakkene legges under `%LOCALAPPDATA%\DRAGEN\python-packages`, separat for hver
Windows-bruker, Python-versjon og pakkeversjon. Kildekoden kan ligge på fellesområdet.
Gamle `.felles-packages` i programmappen brukes eller endres ikke.
NumPy og pandas installeres ikke av DRAGEN. Dette bevarer isolasjonen fra HemaFrag.

Hvis `wheelhouse` følger mappen, brukes den automatisk uten nett. Lokal installasjon kan
styres med `INSTALL_DRAGEN.cmd --offline` eller `--online`. Vanlig oppstart installerer ingenting.
En reparasjon lager en ny lokal pakkemappe. Appen bytter til den først etter at
alle versjoner er kontrollert; tidligere pakker beholdes urørt. Dermed trenger
installasjonen ikke å flytte en mappe som en kollega eller en annen appprosess bruker.
Hver bruker kjører **INSTALL_DRAGEN.cmd** én gang før sin første oppstart.

Feil vises i konsollen med loggbane. FELLES-loggen ligger normalt i
`work/launcher-logs/felles.log`; hvis mappen ikke er skrivbar brukes en lokal reservemappe.
Ved feilsøking oppgis feilmeldingen og Python-versjonen fra FELLES, samt om Ivanti-vinduet åpnet.

## Innlogging og data

E-post og passord lagres i Windows Credential Manager. Eksisterende appdata og profiler
har samme lagringssted. Innlogging og eventuelle MFA-steg fullføres i databasevinduet.
Endringene her endrer ikke en annen apps installasjon eller Windows-policyer.
