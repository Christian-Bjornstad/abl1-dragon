# DRAGEN ELN and evidence update

User request, 2026-10-29: import an Excel list from ELN 2025 Table 5 in Settings, flag matching variants, display three-letter amino acids, color IGV reads by read strand, improve database login/search and report images, include source NM/NP accessions.

Architecture: retain Python/PyQt, seven dependencies and installed Edge. Preserve internal one-letter identities for existing exact-allele searches; use a dedicated display formatter. An imported watchlist is copied to per-user appdata and matched by normalized ABL1 protein substitution, with source and CML scope visible. Report evidence carries source accessions without presenting unrelated isoforms as the analytical transcript. Credentials only Windows Credential Manager; never repository or artifacts.

## Implementation plan
- [x] Extract and visually verify Table 5; deliver one editable, importable workbook with 29 expanded substitutions and source.
- [x] Test and implement strict watchlist import, persistence, matching, Settings action, UI highlight.
- [x] Test and implement lossless three-letter display in UI/report and protein sheet names, preserving source identity and lookup contracts.
- [x] Test IGV alignment config colorBy strand in Edge and exported image.
- [x] Inspect Archer/Solide and existing database flows; test exact-allele search, authentication and robust multi-section/full-page captures, safe evidence persistence, NM/NP reporting. Live T315I: Franklin 18 images, OncoKB 3, MTBP 1. ClinVar exact API result/reference fields confirmed; browser challenge blocks live screenshot verification and requires manual completion.
- [x] Run targeted/full tests, inspect Excel and Edge captures and review diff. Python 3.12: 286 tests, two optional skips; Python 3.14: full suite plus focused import checks. Source/wheel inventories checked. Public-variant workbook contains 22 source images. ClinVar browser challenge remains an explicit manual step.
