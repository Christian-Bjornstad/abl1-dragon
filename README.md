# DRAGEN

Python-app for gjennomgang av BCR::ABL1-varianter fra DRAGEN amplicon.
Mappeimport, variantliste, lokal IGV, databaseoppslag og én Excel-fane.

## Start på Windows

Krever Python 3.12–3.14, 64 bit.

1. Last ned og pakk ut [offline-pakken](https://github.com/Christian-Bjornstad/abl1-dragon/releases/latest).
2. Kjør **Installer ABL1.cmd**.
3. Kjør **Start ABL1.cmd**.

[Installasjon, Python FELLES og Edge](docs/INSTALL.md).
[Første test på jobb-PC](docs/JOBBPC_TEST.md).

## Bruk

Velg analysemappe. Appen finner hard-filtered VCF, tilhørende QC og indekserte
BAM/CRAM-filer. Standardutvalget viser PASS og kodende kontrollkandidater.
Alle opprinnelige kall finnes under **Alle**.

Velg variant og åpne **IGV** i venstremenyen. Lesningsvisningen bruker hele
hovedflaten. Analysesiden har en hendelseslogg. GRCh37/hg19 FASTA med .fai velges i
**Innstillinger** dersom den ikke finnes i analysemappen. Referansen
kontrolleres mot hg19 chr9 før lesningene vises.

**Søk i databaser** slår opp valgt allel. Kort kildestatus vises under variantlisten. Innstillinger samler kildevalg og
innlogging. Prøvenavn, VCF og alignments sendes ikke til databasene.
**Eksporter Excel** lager én fane med det synlige utvalget og oppslagsresultater.

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
