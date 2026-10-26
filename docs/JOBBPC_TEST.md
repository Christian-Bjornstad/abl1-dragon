# Første test på jobb-PC

Pakk ut hele offline-pakken til en fast, skrivbar mappe. Ikke start direkte i ZIP.
Bruk først en lokal testanalyse som er godkjent for metodeutprøving.

## Python FELLES

1. Kjør **INSTALL_DRAGEN.cmd**. Python FELLES åpnes via Ivanti; lim inn med Ctrl+V og trykk Enter.
2. Lukk FELLES etter installasjon. Kjør **START_DRAGEN.cmd** og lim inn i det nye FELLES-vinduet.

På PC uten Ivanti bruker de samme filene lokal Python. Det er ingen egen kontrollfil. Feil og loggbane vises ved installasjon eller start.

## Kontroller i appen

- Programmet starter tomt. Velg analysemappen og kontroller prøvenavn og antall kall.
- Bytt mellom **PASS + kandidater**, **PASS**, **Kandidater** og **Alle**.
- Velg lokal GRCh37 FASTA i **Innstillinger** ved behov. Kontroller IGV for en prøve med indeks.
- Velg en variant og bruk **Søk i databaser**. Kontroller at treff og manglende tilgang skilles.
- Merk to varianter og eksporter Excel. Arbeidsboken skal ha ett ark per merket prøve/variant, med proteinvariant som navn og uten oversiktsark. Kontroller riktig prøve, AF/DP og IGV-bilde i hvert ark. Manglende bilder eller tilgang skal angis.
- Fullfør eventuell databaseinnlogging under **Innstillinger**. Tilgang til kildene kan kreve egne avtaler.
- Kontroller jobbkonto og Microsoft-synk. Edge kan automatisk koble en Windows-konto
  til en ny profilmappe; egen mappe alene bekrefter ikke at synk er avslått.

## Hvis noe stopper

Noter hvilken CMD-fil og hvilket trinn som feilet. FELLES-kontrollen skriver
`work/launcher-logs/felles-check.json`; feil logges i `felles.log` i samme mappe.
Vanlig Python bruker `bootstrap.log`. En reservebane vises hvis mappen er skrivebeskyttet.

Rapportene inneholder lokale filbaner og tekniske opplysninger. Hold dem lokalt til
du har kontrollert innholdet. Passord, tokens og nettleserprofiler skal ikke deles.

Dette er en teknisk pilot. Jobb-PC-testen erstatter ikke klinisk metodevalidering.
