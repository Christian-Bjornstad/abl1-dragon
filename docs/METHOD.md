# Metode

Programmet er en teknisk arbeidsflate. Det er ikke en klinisk validert analysemetode. Et VCF PASS-flagg, et databasefunn eller en høy observert fraksjon gir ikke i seg selv et rapporterbart klinisk resultat.

## Offentlig demo

`scripts/generate_demo.py` lager DEMO-A og DEMO-B med tre oppdiktede SNV-poster ved offentlig kjente ABL1-koordinater. Nabobasene i DEMO-A demonstrerer at VCF-marginaler ikke avgjør haplotype. DEMO-B demonstrerer presentasjon ved lavere oppdiktet informativ dybde. Ingen tall er hentet fra biologiske prøver. Det finnes ingen demo-QC, lesningsstøtte, haplotyper, assay-BED, innsendte kontrollresultater eller kliniske kildebilder i pakken.

`load_pilot()` beholdes som intern API-kompatibilitet, men returnerer denne eksplisitt syntetiske demonstrasjonen med `is_pilot=False`. Dermed får ingen demo eller vanlig filimport tilgang til et tidligere pakket lesningsgrunnlag. `is_demo(session)` identifiserer en tydelig merket demonstrasjon og gir ikke tillit til eventuelle vedlagte lesningsfiler.

## Referanse og variantdata

Kun eksplisitt GRCh37/hg19 og transkript NM_005157.6 støttes. Lokal genomisk REF kontrolleres før SNV-konsekvens beregnes. Ved avvik sperres proteinannotasjonen. Manglende verdier beholdes som manglende. FORMAT/AF, FORMAT/DP, INFO/DP og AD holdes adskilt; AF beregnes ikke fra splittet AD. FILTER `.` betyr ikke evaluert.

Referansen består av offentlig hg19 chr9-sekvens og RefSeq-nummerering. Ingen kliniske assay- eller primerintervaller følger med. Offentlige kilder: [UCSC hg19 chr9](https://hgdownload.soe.ucsc.edu/goldenPath/hg19/chromosomes/chr9.fa.gz) og [RefSeq NM_005157.6](https://www.ncbi.nlm.nih.gov/nuccore/NM_005157.6).

## Valgfri lesningsanalyse

GUI-et kan vise nye BAM/CRAM-filer direkte i lokal IGV.js. Filene finnes ved
mappeimport; @RG-prøvenavn, hg19-header og lokal referansesekvens kontrolleres
før visning. Referanse, indeks og alignment leveres kun over en begrenset lokal
127.0.0.1-tjener med tilfeldig token. Ingen referanse lastes automatisk fra nettet.
Lagre bilde eksporterer et PNG av viseren. Dette beregner ikke fragmentfase.

CLI-et nedenfor kan i tillegg beregne eksplisitt lesningsstøtte og kodonfase:

```text
python engine/analyze.py --input /lokal/kjoring --assembly GRCh37 \
  --alignments /lokal/alignments --reference /lokal/referanse/chr9.fa \
  --output /lokal/analyse/ny.json
```

Krever lokal `pysam` fra `engine/requirements-read-evidence.txt`, indekserte filer navngitt `<sample>[_tumor].bam` eller `.cram`, og komplett lokal hg19 chr9 FASTA med `.fai`. FASTA-kromosomlengde og MD5 kontrolleres. CRAM krever samsvarende M5 i header. Ingen ekstern referanse hentes automatisk.

Mapped primære alignments brukes; sekundære, supplementære og QC-fail alignments utelates. Duplikatflaggede reads beholdes og telles særskilt. Det beregnes lokal støtte ved importerte SNV-er og hele kodon 315. Et komplett kodon krever sammenhengende query-baser på samme alignment. Samstemte observasjoner grupperes etter read-gruppe og query-name; uenige grupper oppgis separat. Fragmentfraksjoner bruker samstemte grupper som nevner, med totalt vurderte grupper og uenige grupper i egne felt.

Disse fragmentene er ikke unike opprinnelige molekyler. Kvalitetsgrensene er tekniske følsomhetssjekker, ikke validerte akseptgrenser eller VAF-er. Motoren gjør ingen FASTQ-realignment, UMI-korreksjon, analyse av fusjonskobling, generell indelmodell eller klinisk klassifikasjon. Kliniske konklusjoner krever relevant assaygrunnlag, validering og faglig vurdering.

## Testgrunnlag

Standardutvalget **PASS + kandidater** er teknisk sortering. En kontrollkandidat
har kodende annotasjon, samsvarende REF og observerte ALT-reads, men callerens
opprinnelige FILTER beholdes. REF-avvik, transkriptfortsettelse og øvrige kall
vises under **Alle**. Ingen AF-grense brukes som validert deteksjonsgrense.

Databaseoppslag krever eksakt bygg/posisjon/REF/ALT. ClinVar-klassifikasjon og
onkologiske evidensnivåer er ulike akser. Fravær av treff er forskjellig fra
nettverksfeil og manglende tilgang. Excel beholder kilde og tidspunkt i cellekommentarer.

Offentlige regresjonstester dekker syntetisk demoidentitet, referanse-/byggkontroll, flerallelisk import, manglende felt, manglende fase, prosjektfingeravtrykk, bevaring av nyere lokale vurderinger og formelsikker CSV-/Excel-eksport. Valgfri pysam-test lager sin egen lille BAM; ingen innsendte sekvenseringsfiler brukes.

Qt- og oppstartstester viser programatferd i testmiljøet. De dokumenterer ikke autentisering, databaselisens, faktisk Edge-/WebEngine-bruk eller kompatibilitet med et bestemt institusjonsmiljø.
