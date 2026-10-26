"""Local IGV in an app-owned Microsoft Edge window; no Qt renderer required."""
from pathlib import Path
import time
from .database_browser import EdgeBrowser
from .lookup_browser import _EdgeContext,debugging_policy


class EdgeIgv:
    def __init__(self,data_dir,*,edge=None,context_factory=None):
        self.folder=Path(data_dir).resolve();self.edge=edge or EdgeBrowser(self.folder)
        self.factory=context_factory or _EdgeContext;self.context=None

    def open(self,server,cancel):
        from .igv_live import viewer_url_allowed
        warning=self.edge.diagnostics().get('warning') or debugging_policy()
        if warning:raise RuntimeError(warning)
        executable=self.edge.executable_path()
        if executable is None:raise RuntimeError('Microsoft Edge ble ikke funnet.')
        url=server.url('viewer.html')
        if not viewer_url_allowed(url,server):raise ValueError('IGV-serveren er ikke aktiv.')
        if cancel.is_set():raise InterruptedError()
        self.context=self.factory(executable,self.folder/'IgvEdge')
        try:
            if cancel.is_set():raise InterruptedError()
            # Only this owned target receives the validated, revocable local URL.
            self.context._page_call('Page.navigate',{'url':url})
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                if cancel.is_set():raise InterruptedError()
                title=self.context.evaluate('document.title')
                if title=='ABL1_IGV_READY':return
                if isinstance(title,str) and title.startswith('ABL1_IGV_ERROR'):
                    raise RuntimeError('IGV i Edge kunne ikke lese sporene. Se meldingen i Edge-vinduet.')
                time.sleep(.2)
            raise RuntimeError('IGV i Edge ble ikke ferdig lastet innen 45 sekunder.')
        except BaseException:
            self.close();raise

    def svg(self):
        if self.context is None:raise RuntimeError('IGV-vinduet er lukket.')
        svg=self.context.evaluate('window.dragonBrowser ? window.dragonBrowser.toSVG() : null')
        if not isinstance(svg,str) or len(svg)>30_000_000:raise ValueError('IGV-bildet kunne ikke leses fra Edge.')
        return svg

    def close(self):
        context,self.context=self.context,None
        if context is not None:context.close()
