# Databaseoppslag

Merk varianter og velg **Søk i databaser**. Samme GRCh37-allel søkes én gang på
tvers av prøver. Resultat og bilder lagres lokalt etter hvert som de blir klare.
Et nytt søk henter nye svar; tidligere oppslag gjenopprettes med sitt tidspunkt.
Når alle bilder fra en kilde er lagret, lukkes appens søkevindu automatisk.
Profilen beholdes. Ved innlogging, nettleserkontroll eller delvis bildeuttak blir
vinduet stående slik at oppslaget kan fullføres. Ferdige bilder fra andre kilder
beholdes når **Hent bilder fra åpne sider** brukes.

| Kilde | Oppslag og bilder |
| --- | --- |
| ClinVar | Eksakt GRCh37-posisjon, REF/ALT og gjeldende VCV-post. Hele siden hentes som lesbare bildeseksjoner når nettstedet er tilgjengelig. |
| OncoKB | Eksakt genomisk HGVS med GRCh37. Onkogenisitet og biologisk effekt leses fra variantens egne resultatfelt. Sideutsnitt inkluderer innhold under første skjermbilde. |
| Franklin | Hjemmesøk med hg19 og Somatic, som i Archer. ACMG-/onkogenisitetsvisninger, evidenskort og tilgjengelige prediksjons-/populasjonsvisninger lagres med egne bildetekster. |
| MTBP | Én variant og tilfeldig DRAGEN-ID per analyse, med sykdomskategorien Blood. Et eksplisitt avvist transkriptsøk kan prøves med GRCh37-HGVS. Uklart svar sendes aldri på nytt automatisk. |

MTBP-analysen kan bruke tid. Appen venter normalt inntil 90 sekunder etter
innsending. **Analyse venter** betyr at neste søk skal hente samme analyse;
en rapport som er fjernet fra kontoen erstattes ikke med en annen rapport.
Rapporten oppgir om MTBP-treffet bygger på protein, cDNA eller kontrollert GRCh37-allel. Private
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

- 15. november 2026: ClinVar ga fem bilder og OncoKB tre, med automatisk
  lukking etter lokal lagring. Etter korrigering av det lagrede Franklin-passordet
  ble innlogging bekreftet fra konto-/organisasjonsfeltet på nettstedet.
  Innlogget Thr315Ile-oppslag ga 18 bilder, kontrollert innebygd i Excel.
  Appen viser avvist innlogging og går ikke videre anonymt når en konto er lagret.
- MTBP: offentlig Met244Val ga ett lesbart variantbilde og automatisk lukking.
  Ny Edge-oppstart hentet samme analyse uten ny innsending. Excel-bilder og
  arknavn ble kontrollert for disse oppslagene. Ingen pasientfiler ble sendt.
- Appens faktiske søkeknapp og bakgrunnsjobb ble kjørt to ganger på rad med
  ClinVar og OncoKB. Begge rundene ga åtte bilder, lukkede søkevindu og
  Excel-arket Thr315Ile med alle åtte bilder.
- Regresjonstester dekker automatisk lukking etter lagring, gjenåpning,
  midlertidig mislykkede bilder, uferdige Franklin-paneler, avbrutt bildeuttak,
  negativt resultat under bildeuttak og MTBP-analyser etter omstart.
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
