# Første test på jobb-PC

Last ned hele main-branchen fra GitHub og pakk ut til en fast, skrivbar mappe. Ikke start direkte i ZIP.
Bruk først en lokal testanalyse som er godkjent for metodeutprøving.

## Python FELLES

1. Kjør **INSTALL_DRAGEN.cmd**. Python FELLES åpnes via Ivanti; lim inn med Ctrl+V og trykk Enter.
2. Lukk FELLES etter installasjon. Kjør **START_DRAGEN.cmd** og lim inn i det nye FELLES-vinduet.

Oppstart følger PRONTO: Ivanti hvis tilgjengelig, ellers eksplisitt valgt lokal Python, `.venv` eller Python Launcher. Det er ingen egen kontrollfil. GitHub-kildekoden trenger ikke wheelhouse; installasjonen henter låste pakker ved behov. Feil og loggbane vises ved installasjon eller start.

## Kontroller i appen

- Programmet starter tomt. Velg analysemappen og kontroller prøvenavn og antall kall.
- Bytt mellom **PASS + kandidater**, **PASS**, **Kandidater** og **Alle**.
- Kontroller at **Innstillinger** har valgt medfølgende `reference/hg19/chr9.fa` automatisk. Kontroller IGV for en prøve med indeks, også uten nettilgang.
- Velg en variant og bruk **Søk i databaser**. Kontroller at treff og manglende tilgang skilles.
- Merk to varianter og eksporter Excel. Arbeidsboken skal ha ett ark per merket prøve/variant, med proteinvariant som navn og uten oversiktsark. Kontroller riktig prøve, AF/DP og IGV-bilde i hvert ark. Manglende bilder eller tilgang skal angis.
- Fullfør eventuell databaseinnlogging under **Innstillinger**. Tilgang til kildene kan kreve egne avtaler.
- Lukk appens databasevindu og åpne det på nytt fra **Innstillinger**. Andre databaseøkter skal beholde sin innloggingsstatus.
- Etter innlogging eller manuell nettleserkontroll: vis riktig variant i databasevinduet og bruk **Hent bilder fra åpne sider**. Kontroller at kildestatus viser **bilde klart**, og at bildet følger med i Excel.
- Kontroller jobbkonto og Microsoft-synk. Edge kan automatisk koble en Windows-konto
  til en ny profilmappe; egen mappe alene bekrefter ikke at synk er avslått.

## Hvis noe stopper

Noter hvilken CMD-fil og hvilket trinn som feilet. FELLES-kontrollen skriver
`work/launcher-logs/felles-check.json`; feil logges i `felles.log` i samme mappe.
Vanlig Python bruker `bootstrap.log`. En reservebane vises hvis mappen er skrivebeskyttet.

Rapportene inneholder lokale filbaner og tekniske opplysninger. Hold dem lokalt til
du har kontrollert innholdet. Passord, tokens og nettleserprofiler skal ikke deles.

Dette er en teknisk pilot. Jobb-PC-testen erstatter ikke klinisk metodevalidering.
