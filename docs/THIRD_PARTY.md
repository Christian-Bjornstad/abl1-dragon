# Lisenser og ressurser

DRAGEN er distribuert under GPL-3.0. Se [LICENSE](../LICENSE).

IGV-sporene `assets/igv/abl1.bed` og `protein.bed` er generert fra den medfølgende offentlige RefSeq-kartleggingen NM_005157.6 i hg19. Proteinsporet viser referansetranslasjon. Kromosombånd for chr9 kommer fra [UCSC hg19 cytoBand](https://hgdownload.soe.ucsc.edu/goldenPath/hg19/database/cytoBand.txt.gz). Bygges med `scripts/build_igv_annotations.py`.

Pillow brukes til PNG-bilder i Excel, under [HPND-lisensen](https://pillow.readthedocs.io/en/stable/about.html#license).

PyQt6 og PyQt-WebEngine bruker GPLv3 eller kommersiell lisens.
Qt-bibliotekenes egne lisenser følger deres distribusjon.
[Riverbank](https://www.riverbankcomputing.com/software/pyqt/intro).
openpyxl bruker MIT-lisens. Valgfri pysam bruker MIT-lisens og inkluderer
komponenter med egne lisensvilkår. Pakkenes lisensfiler skal følge binærleveranser.
`websocket-client` bruker Apache-2.0-lisens og benyttes til den lokale,
appstyrte Edge-forbindelsen. [Prosjekt og lisens](https://github.com/websocket-client/websocket-client).

Ikonet i `assets/brand` ble laget for dette prosjektet med imagegen.
Master: `abl1-dragon.png`. Windows-ikon: `abl1-dragon.ico`.
Fargene er lilla og grå; motivet kombinerer en drage og en DNA-heliks.

Referansesekvensen og koordinatkartet gjelder GRCh37/hg19 og NM_005157.6,
fra offentlige referanser. Kildeadresser er angitt i `engine/reference.json`.
Demoen og alle medfølgende testtilfeller er syntetiske.

`assets/reference/chr9.fa.gz` og `chr9.fa.fai` inneholder hele offentlige
[UCSC hg19 chr9](https://hgdownload.soe.ucsc.edu/goldenPath/hg19/chromosomes/chr9.fa.gz),
141 213 431 baser. Sekvensen er komprimert på nytt uten endringer i FASTA-innholdet.
Sekvens-MD5: `3e273117f15e0a400f01055d9f393768`. SHA-256 for arkiv,
utpakket FASTA og indeks står i `assets/reference/manifest.json`.
Dette er human referansesekvens, uten pasient- eller analysedata.
Pakken kan bygges på nytt fra en lokal FASTA med `scripts/bundle_chr9.py`.

IGV.js 3.8.9 distribueres lokalt med MIT-lisens. Lisens og kildeproveniens
følger `assets/igv`. [IGV.js](https://github.com/igvteam/igv.js).
