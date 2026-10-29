# Databaseoppslag

Merk varianter og velg **Søk i databaser**. Samme GRCh37-allel søkes én gang på
tvers av prøver. Resultat og bilder lagres lokalt etter hvert som de blir klare.
Et nytt søk henter nye svar; tidligere oppslag gjenopprettes med sitt tidspunkt.

| Kilde | Oppslag og bilder |
| --- | --- |
| ClinVar | Eksakt GRCh37-posisjon, REF/ALT og gjeldende VCV-post. Hele siden hentes som lesbare bildeseksjoner når nettstedet er tilgjengelig. |
| OncoKB | Eksakt genomisk HGVS med GRCh37. Onkogenisitet og biologisk effekt leses fra variantens egne resultatfelt. Sideutsnitt inkluderer innhold under første skjermbilde. |
| Franklin | Hjemmesøk med hg19 og Somatic, som i Archer. ACMG-/onkogenisitetsvisninger, evidenskort og tilgjengelige prediksjons-/populasjonsvisninger lagres med egne bildetekster. |
| MTBP | Én variant og tilfeldig DRAGEN-ID per analyse, med sykdomskategorien Blood. Et eksplisitt avvist transkriptsøk kan prøves med GRCh37-HGVS. Uklart svar sendes aldri på nytt automatisk. |

MTBP-analysen kan bruke tid. **Analyse venter** betyr at neste søk skal hente samme
analyse. Rapporten oppgir om MTBP-treffet bygger på protein, cDNA eller kontrollert GRCh37-allel. Private
MTBP-rapportadresser eksporteres ikke. Rapporter slettes ikke fra MTBP av appen.

Excel lagres i én fil per prøve, `<prøvenavn>_DRAGEN_Resultater.xlsx`, med
ett ark per valgt variant og proteinvariant som arknavn. Hvert
ark inneholder variantdata, kildesvar, navngitte databasebilder og prøvens IGV-bilde.
Det opprettes ikke oversiktsark. Manglende delbilder vises både i appen og i Excel.
Kildenes versjonerte NM-/NP-referanser og accession-kvalifiserte HGVS følger
variantarket. Analysens NM_005157.6 / NP_005148.2 holdes adskilt fra andre
isoformer i kildene. MTBP oppgir «academic research use only»; dette beholdes
i kildesvaret når teksten finnes i rapporten.

## Verifisert under utviklingen

- Innlogget T315I-oppslag i ekte Edge: Franklin med 18 bilder, OncoKB med tre
  sideutsnitt og MTBP med kontrollert genomisk treff og variantbilde. Testet
  29. oktober 2026 med offentlig allel; ingen pasientfiler sendt.
- ClinVar: eksakt T315I-treff, VCV000012624.3, med versjonerte NM-/NP-referanser.
  Nettleserkontrollen slapp gjennom etter venting; både gjenopptatt bildeuttak
  og et nytt vanlig oppslag ga fem lesbare sideutsnitt. Alle fem ble kontrollert
  og funnet innebygd i Excel-arket Thr315Ile. Testet 29. oktober 2026.
  En eventuell ny kontrollside lagres ikke som variantbilde.
- Kontrollerte tester dekker blant annet variantbytte under bildeuttak, tomme
  bilder, delvise uttrekk, gjenoppretting, MTBP-kø og avbrutt innsending.
- Innloggingsskjemaene er kontrollert i Edge med syntetiske skjemaer og blokkert
  nettverk. Franklin/OncoKBs JavaScript-skjemaer får ikke sende passord via GET;
  appen venter på en bekreftet økt etter én innsending.

Tilgang og nettleserkontroll på jobb-PC må prøves der.
Se [jobb-PC-testen](JOBBPC_TEST.md).
