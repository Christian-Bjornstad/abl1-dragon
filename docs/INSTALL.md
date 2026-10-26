# Installasjon og start

Pakk ut hele DRAGEN-mappen til et fast, skrivbart sted.

1. Kjør **INSTALL_DRAGEN.cmd** én gang.
2. Kjør **START_DRAGEN.cmd** for å åpne appen.

Det finnes bare disse to CMD-filene. Python og avhengigheter kontrolleres under installasjon og oppstart.

## Jobb-PC / Python FELLES

Som i MolStat åpner filene Python FELLES via Ivanti (`pwrgate.exe`, program-ID 15694)
og kopierer riktig kommando til utklippstavlen. Lim inn med **Ctrl+V** i Python FELLES
og trykk **Enter**. Etter installasjon lukkes Python FELLES. Start appen med
**START_DRAGEN.cmd** og lim inn kommandoen i det nye vinduet.

`install.py` og `start.py` kjører i samme Python-interpreter som FELLES. Installasjonen
bruker offline-hjulene i `wheelhouse` og appens egen `.felles-packages`. Globale Python-pakker
endres ikke. Python 3.12–3.14, Windows 64 bit støttes; MolStat-oppsettet bruker FELLES 3.14.
Et nytt FELLES-vindu uten innlastet Qt kreves.

Feil vises i konsollen med bane til loggen i `work/launcher-logs/felles.log`.
Hvis mappen ikke er skrivbar brukes en lokal midlertidig loggmappe. Ingen separat kontrollfil kreves.

IT kan overstyre Ivanti-banen med `ABL1_IVANTI` og program-ID med `ABL1_IVANTI_APP_ID`.
Appen endrer ikke Windows-policyer eller PowerShell ExecutionPolicy.

## PC uten Ivanti

De samme to CMD-filene finner lokal Python og bruker et isolert `.venv`. Medfølgende
offline-pakker brukes under installasjon. Vanlig start laster ikke ned eller installerer noe.

For å velge lokal Python på en PC som også har Ivanti:

```cmd
set DRAGEN_LOCAL_PYTHON=1
INSTALL_DRAGEN.cmd --python "C:\Python314\python.exe" --offline
START_DRAGEN.cmd --data-dir "D:\LokaleAnalyser\DRAGEN"
```

Lokale oppstartsfeil skrives til `work/launcher-logs/bootstrap.log`. Flytt hele
programmappen før installasjon; ikke flytt et ferdig `.venv` mellom PC-er.

## Fra kildekoden

Git-repoet inneholder ikke binære avhengigheter. Offline-utgaven ligger under GitHub Releases.
På utvikler-PC uten Ivanti kan `INSTALL_DRAGEN.cmd --online` laste ned låste avhengigheter.

## Edge og innlogging

E-post og passord kan lagres under **Innstillinger**, i Windows Credential Manager.
Status er separat per database. MFA og ukjente SSO-skjemaer fullføres i Edge.
Appen bruker egne nettleserprofiler og respekterer Edge-policy. En egen profil hindrer
ikke nødvendigvis automatisk Microsoft-innlogging eller synk; kontroller riktig jobbkonto.
Nettleserprofiler skal ikke deles eller legges i Git.
