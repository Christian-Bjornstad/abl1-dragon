# DRAGEN

Python-app for gjennomgang av BCR::ABL1-varianter fra DRAGEN amplicon.
Mappeimport, variantutvalg, lokal IGV, databaseoppslag og Excel med ett ark per variant.

## Start på Windows

Krever Python 3.12–3.14, 64 bit.

1. Last ned hele [main-branchen](https://github.com/Christian-Bjornstad/abl1-dragon/archive/refs/heads/main.zip) og pakk ut.
2. Kjør **INSTALL_DRAGEN.cmd**.
3. Kjør **START_DRAGEN.cmd**.

Start og installasjon følger PRONTOs Python FELLES-mønster. På jobb-PC åpnes FELLES via
Ivanti; lim inn med Ctrl+V og trykk Enter. Ved installasjon fra kildekoden hentes de låste
pakkene automatisk. Lukk FELLES etter installasjon før appen startes i et nytt vindu.

[Installasjon, Python FELLES og Edge](docs/INSTALL.md).
[Første test på jobb-PC](docs/JOBBPC_TEST.md).

## Bruk

Velg analysemappe. Appen finner hard-filtered VCF, tilhørende QC og indekserte
BAM/CRAM-filer. Standardutvalget viser PASS og kodende kontrollkandidater.
Alle opprinnelige kall finnes under **Alle**. Kryss av variantene som skal søkes opp og rapporteres.
**Merk synlige** merker hele det viste utvalget. Merking beholdes når listen filtreres.

Velg variant og åpne **IGV** i venstremenyen. Lesningsvisningen bruker hele
hovedflaten, med standardzoom og 200 bp-oversikt. Dekning, grå lesninger med baseavvik,
referansesekvens og NM_005157.6 gen-/proteinspor vises lokalt.
Analysesiden har en hendelseslogg. GRCh37/hg19 FASTA med .fai velges i
**Innstillinger** dersom den ikke finnes i analysemappen. Referansen
kontrolleres mot hg19 chr9 før lesningene vises.

**Søk i databaser** slår opp merkede alleler. Samme allel i flere prøver søkes én gang.
Kort kildestatus vises under variantlisten. Innstillinger samler kildevalg og innlogging.
E-post og passord lagres i Windows Credential Manager per lokal appdatamappe. Passord
ligger ikke i innstillingsfilen og fylles bare inn i kontrollerte innloggingsskjemaer
på riktig databasevert. MFA og endrede/eksterne SSO-skjemaer fullføres i Edge.
**Glem** fjerner den lagrede innloggingen; aktive nettstedssesjoner kan fortsatt være innlogget.
Prøvenavn, VCF og alignments sendes ikke til databasene.

**Eksporter Excel** lager ett ark per merket prøve/variant, navngitt etter proteinvarianten,
uten oversiktsark. AF, ALT/DP, FILTER, kildeinformasjon og tilgjengelige kildebilder følger med.
Et standardbilde av riktig prøves IGV tas automatisk for hver variant under eksporten.
Ulike prøver med samme proteinvariant får egne ark. Manglende bilde/tilgang angis i arket.
Databasebilder tas bare når nettsiden bekrefter riktig allel; et treff i tekst alene er
ikke tilstrekkelig. MTBP-innlogging støttes, men automatisk MTBP-analyse er ikke implementert.
Ingen ekstern rapport opprettes eller slettes av MTBP-adapteren.

Annotasjon bruker GRCh37/hg19 og NM_005157.6. PASS er caller-status.
Kontrollkandidater er teknisk sortering uten validert deteksjonsgrense.
VCF alene dokumenterer ikke fase eller dekning ved negative posisjoner.
Appen er ikke klinisk validert. Medfølgende tester og CLI-selvtesten bruker syntetiske data.
[Metode og avgrensning](docs/METHOD.md).

Prøvefiler, prosjekter og nettleserprofiler lagres utenfor repoet.

## Utvikling

```cmd
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-desktop.txt
.venv\Scripts\python start_abl1.py
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py"
```

Valgfrie lesningstester med pysam på Linux:
`python tests/optional/read_evidence_checks.py`.

GPL-3.0. Se [LICENSE](LICENSE) og [tredjepartsressurser](docs/THIRD_PARTY.md).
