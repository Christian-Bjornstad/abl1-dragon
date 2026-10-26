# Mappe til rapport

Hovedbildet starter uten analyse. En valgt mappe søkes rekursivt etter hard-filtered VCF, prøvebundne QC-filer og indekserte BAM/CRAM-filer. Genomreferansen er GRCh37/hg19 og transkriptet NM_005157.6.

Standardutvalget viser PASS og filtrerte kodende kandidater med ALT-observasjoner. Original FILTER beholdes. REF-avvik, transkriptfortsettelse og ukjente annotasjoner finnes under Alle. Kategorier er teknisk sortering, ikke en klinisk klassifisering eller validert deteksjonsgrense.

Valgt variant vises i lokal IGV. Databaseoppslag sendes eksplisitt fra valgt allel; prøvenavn og analysefiler inngår ikke. Innstillinger samler kildevalg og innlogging. Manglende treff, manglende tilgang og feil skal være forskjellige resultater.

Merk de variantene som skal søkes opp og rapporteres. Merking beholdes ved filtrering og gjelder per prøve og allel. Databaseoppslag dedupliseres per genomisk allel. Excel inneholder ett ark per merket prøve/variant, med proteinvariant som arknavn, caller-tall, kildeinformasjon og tilgjengelige databasebilder. Standardbilder fra riktig prøves IGV tas automatisk under eksport. Ingen oversiktsfane eller manuell vurderingsblankett. Fasekrav og originaldata beholdes i proteinfeltets kommentar.

Innlogging lagres i Windows Credential Manager, med separat nøkkel per lokal appdatamappe og kilde. Passord skrives ikke i JSON, logger, rapporter eller installasjonspakker. Bare forventet HTTPS-vert og synlig, entydig innloggingsskjema kan fylles. MFA og ukjente SSO-flyter håndteres manuelt i Edge. Passordfeltene er maskert, og lagret passord vises som plassholder.

Databasebilder krever et identitetskontrollert treff før uttak og ny kontroll etter uttak. Endres siden, forkastes bildet. IGV kjører på loopback med riktig prøve og kontrollert referanse. Eksporten laster hver valgte prøve/variant på nytt med standardzoom og fanger alle spor; gamle bilder fra en annen variant gjenbrukes ikke. Utdatert last eller avbrutt eksport ignoreres. Excel erstattes først etter vellykket lagring av hele arbeidsboken.

Gjennomføring: filvalg og kandidater → enkel native arbeidsflate → lokal IGV → faktiske kildeoppslag → én Excel-fane → automatiske tester og kontroll i Windows.
