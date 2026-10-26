# Databaseoppslag

Merk varianter og velg **Søk i databaser**. Samme GRCh37-allel søkes én gang på
tvers av prøver. Resultat og bilder lagres lokalt etter hvert som de blir klare.
Et nytt søk henter nye svar; tidligere oppslag gjenopprettes med sitt tidspunkt.

| Kilde | Oppslag og bilder |
| --- | --- |
| ClinVar | Eksakt GRCh37-posisjon, REF/ALT og gjeldende VCV-post. Nettleserbildet viser klassifikasjonssammendraget når siden er tilgjengelig. |
| gnomAD | GRCh37 / v2.1.1. Eksomer og genomer holdes atskilt. Ingen treff rapporteres som ingen treff, uten å tolke varianten som benign. |
| COSMIC | Eksakt GRCh37/NM_005157/cDNA-kandidat fra det offentlige NLM-utdraget brukes til å åpne riktig mutasjonspost. Portalinnhold og bilde krever tilgang. |
| OncoKB | Eksakt genomisk HGVS med GRCh37. Onkogenisitet og biologisk effekt leses fra variantens egne resultatfelt. Bilde tas etter at siden er ferdig. |
| Franklin | Hjemmesøk med hg19 og Somatic, som i Archer. ACMG-/onkogenisitetsvisninger, evidenskort og tilgjengelige prediksjons-/populasjonsvisninger lagres med egne bildetekster. |
| MTBP | Én variant og tilfeldig DRAGEN-ID per analyse, med sykdomskategorien Blood. Et eksplisitt avvist transkriptsøk kan prøves med GRCh37-HGVS. Uklart svar sendes aldri på nytt automatisk. |

MTBP-analysen kan bruke tid. **Analyse venter** betyr at neste søk skal hente samme
analyse. Rapporten oppgir om MTBP-treffet bygger på protein eller cDNA. Private
MTBP-rapportadresser eksporteres ikke. Rapporter slettes ikke fra MTBP av appen.

Excel har ett ark per valgt prøve/variant med proteinvariant som arknavn. Hvert
ark inneholder variantdata, kildesvar, navngitte databasebilder og prøvens IGV-bilde.
Det opprettes ikke oversiktsark. Manglende delbilder vises både i appen og i Excel.

## Verifisert under utviklingen

- OncoKB: offentlig T315I-oppslag gjennom ekte Edge, lesing av resultatfelt,
  PNG-kontroll, lokal lagring og innbygging av bildet i arket T315I.
- ClinVar: eksakt API-treff. Nettstedet krevde nettleserkontroll på test-PC-en;
  kontrollsiden ble korrekt avvist som rapportbilde.
- gnomAD: T315I ga ingen treff i v2.1.1, og dette ble bevart i rapporten.
  En separat offentlig kontrollallel ga eksakte populasjonstall og et validert
  bilde fra den faktiske gnomAD-siden i Edge.
- Kontrollerte tester dekker blant annet variantbytte under bildeuttak, tomme
  bilder, delvise uttrekk, gjenoppretting, MTBP-kø og avbrutt innsending.

Full gjennomgang av innloggede Franklin-, COSMIC- og MTBP-sider må gjøres med
aktuelle kontoer og tilganger. Se [jobb-PC-testen](JOBBPC_TEST.md).
