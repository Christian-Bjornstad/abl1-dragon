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
        chromosomeOrder: [config.chromosome]
      },
      locus: config.locus,
      showIdeogram: false,
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
        height: 400,
        color: "#82718f",
        showCoverage: true,
        samplingWindowSize: 100,
        samplingDepth: 1000,
        visibilityWindow: 100000,
        filter: {duplicates: false}
      }]
    });
    document.title = "ABL1_IGV_READY";
  } catch (error) {
    const target = document.getElementById("error");
    target.hidden = false;
    target.textContent = "IGV: " + String(error.message || error);
    document.title = "ABL1_IGV_ERROR";
  }
}());
