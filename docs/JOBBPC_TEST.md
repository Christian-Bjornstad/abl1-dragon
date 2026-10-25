# Første test på jobb-PC

Pakk ut hele offline-pakken til en fast, skrivbar mappe. Ikke start direkte i ZIP.
Bruk først en lokal testanalyse som er godkjent for metodeutprøving.

## Python FELLES

1. Kjør **Kontroller med Python FELLES.cmd**, lim inn kommandoen i FELLES og trykk Enter.
   Før første installasjon skal den kunne vise «Installasjon: klar» og «Oppstart: ikke klar».
2. Kjør **Installer med Python FELLES.cmd** på samme måte. Lukk FELLES-vinduet etterpå.
3. Kjør **Start med Python FELLES.cmd** i et nytt FELLES-vindu.

Disse CMD-filene trenger lokal Ivanti-program-ID i `ABL1_IVANTI_APP_ID`.
En separat lokal testpakke kan ha forhåndsutfylte startfiler som setter dette bare
for den aktuelle kjøringen. De endrer ikke Windows-miljø eller register.

På PC med vanlig Python brukes **Installer ABL1.cmd** og **Start ABL1.cmd**.

## Kontroller i appen

- Programmet starter tomt. Velg analysemappen og kontroller prøvenavn og antall kall.
- Bytt mellom **PASS + kandidater**, **PASS**, **Kandidater** og **Alle**.
- Velg lokal GRCh37 FASTA i **Innstillinger** ved behov. Kontroller IGV for en prøve med indeks.
- Velg en variant og bruk **Søk i databaser**. Kontroller at treff og manglende tilgang skilles.
- Eksporter Excel. Arbeidsboken skal ha én fane med det synlige variantutvalget.
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
