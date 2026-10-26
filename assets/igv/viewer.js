/* Selected-run data are available only from the private loopback capability URL. */
"use strict";
(async function () {
  try {
    const response = await fetch("config.json", {cache: "no-store"});
    if (!response.ok) throw new Error("IGV-konfigurasjonen kunne ikke leses.");
    const config = await response.json();
    const url = name => new URL(name, window.location.href).href;
    window.dragonBrowser = await igv.createBrowser(document.getElementById("igv"), {
      loadDefaultGenomes: false,
      genomeList: [],
      reference: {
        id: "abl1-local-grch37",
        name: "hg19 / GRCh37",
        fastaURL: url("reference.fa"),
        indexURL: url("reference.fa.fai"),
        chromosomeOrder: [config.chromosome],
        cytobandURL: url('cytoband.txt')
      },
      locus: config.locus,
      showIdeogram: true,
      showSequence: false,
      showSVGButton: false,
      showCenterGuide: true,
      showTrackLabels: true,
      showChromosomeWidget: false,
      tracks: [{
        name: config.sample,
        type: "alignment",
        format: config.kind,
        url: url(config.alignment),
        indexURL: url(config.index),
        height: 420,
        order: 1,
        color: "#C3C3C3",
        colorBy: "none",
        coverageColor: "#A8A8A8",
        coverageTrackHeight: 55,
        showMismatches: true,
        showAllBases: false,
        displayMode: "EXPANDED",
        alignmentRowHeight: 12,
        showCoverage: true,
        samplingWindowSize: 100,
        samplingDepth: 1000,
        visibilityWindow: 100000,
        filter: {duplicates: false}
      },
      {type: 'sequence', name: 'Sekvens', order: 2},
      {type: 'annotation', format: 'bed', name: 'Protein · NM_005157.6', url: url('protein.bed'), indexed: false,
        order: 3, height: 45, displayMode: 'COLLAPSED', color: '#412D73'},
      {type: 'annotation', format: 'bed', name: 'ABL1 · NM_005157.6', url: url('abl1.bed'), indexed: false,
        order: 4, height: 55, displayMode: 'EXPANDED', color: '#412D73'}]
    });
    document.getElementById('reset-view').onclick = () => window.dragonBrowser.search(config.locus);
    document.getElementById('wider-view').onclick = () => window.dragonBrowser.search(config.widerLocus);
    document.title = "ABL1_IGV_READY";
  } catch (error) {
    const target = document.getElementById("error");
    target.hidden = false;
    target.textContent = "IGV: " + String(error.message || error);
    document.title = "ABL1_IGV_ERROR";
  }
}());
