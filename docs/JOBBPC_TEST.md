# Første test på jobb-PC

Pakk ut hele offline-pakken til en fast, skrivbar mappe. Ikke start direkte i ZIP.
Bruk syntetisk demo til kontrollene nedenfor.

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

- Åpne DEMO-A. Det skal vises to av totalt tre variantposter. Ingen QC eller lesninger følger demoen.
- Skriv et testnotat, lagre prosjekt, lukk appen og åpne prosjektet igjen.
- Eksporter Excel. Arbeidsboken skal inneholde tre varianter og testnotatet.
- Under **Kilder og databaser**, kontroller Edge-oppsettet og åpne ønsket kilde.
  Fullfør eventuell innlogging selv. Et åpnet nettsted bekrefter ikke API- eller lisensavtale.
- Kontroller jobbkonto og Microsoft-synk. Edge kan automatisk koble en Windows-konto
  til en ny profilmappe; egen mappe alene bekrefter ikke at synk er avslått.
- Prøv først egne analysefiler etter at demoens import, lagring og eksport virker.

## Hvis noe stopper

Noter hvilken CMD-fil og hvilket trinn som feilet. FELLES-kontrollen skriver
`work/launcher-logs/felles-check.json`; feil logges i `felles.log` i samme mappe.
Vanlig Python bruker `bootstrap.log`. En reservebane vises hvis mappen er skrivebeskyttet.

Rapportene inneholder lokale filbaner og tekniske opplysninger. Hold dem lokalt til
du har kontrollert innholdet. Passord, tokens og nettleserprofiler skal ikke deles.

Dette er en teknisk pilot. Jobb-PC-testen erstatter ikke klinisk metodevalidering.
