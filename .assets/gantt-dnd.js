// Drag & drop directly on Plotly Gantt bars.
// Fixes:
//  - dispatch the event on the EventListener host (NOT document)
//  - use xaxis.p2l(px) -> xaxis.l2d(lin) for pixel->date conversion

(function() {
  function findGraphDiv() {
    return document.querySelector('div.js-plotly-plot');
  }
  function findEventHost() {
    return document.getElementById('gantt_dnd_listener');
  }

  function pxToXISO(gd, px) {
    try {
      const xa = gd._fullLayout.xaxis;
      const lin = xa.p2l(px);        // pixel -> linear
      const dat = xa.l2d(lin);       // linear -> data (ms since epoch for date axis)
      const dt  = new Date(dat);
      return dt.toISOString();
    } catch (e) {
      return null;
    }
  }

  function pyToWorker(gd, py) {
    try {
      const ya = gd._fullLayout.yaxis;
      const cats = (ya && ya.categoryarray) || [];
      if (!ya || !ya.l2p) return null;
      let best = null, bestDist = Infinity;
      for (const name of cats) {
        const p = ya.l2p(name); // data value -> pixel
        const d = Math.abs(p - py);
        if (d < bestDist) { best = name; bestDist = d; }
      }
      return best;
    } catch (e) {
      return null;
    }
  }

  function resolveTaskIdFromNode(gd, rectNode) {
    const curve = rectNode.getAttribute('data-curvenumber');
    const point = rectNode.getAttribute('data-pointnumber');
    if (curve == null || point == null) return null;
    const c = gd.data[+curve];
    if (!c || !c.customdata) return null;
    const cd = c.customdata[+point]; // [TaskId, Worker]
    return cd ? cd[0] : null;
  }

  function install() {
    const gd = findGraphDiv();
    const host = findEventHost();
    if (!gd || !host || gd._ganttDndInstalled) return;
    gd._ganttDndInstalled = true;

    let dragging = null;

    gd.addEventListener('mousedown', function(e) {
      const t = e.target;
      if (!(t && t.tagName === 'rect' && t.hasAttribute('data-pointnumber'))) return;

      const taskId = resolveTaskIdFromNode(gd, t);
      if (!taskId) return;

      const plotArea = gd.querySelector('.cartesianlayer .plot');
      if (!plotArea) return;

      const plotBox = plotArea.getBoundingClientRect();
      dragging = { taskId, plotBox };
      e.preventDefault();
    }, true);

    window.addEventListener('mouseup', function(e) {
      if (!dragging) return;
      const plotArea = gd.querySelector('.cartesianlayer .plot');
      if (!plotArea) { dragging = null; return; }

      const { plotBox, taskId } = dragging;
      const px = e.clientX - plotBox.left; // x inside plot
      const py = e.clientY - plotBox.top;  // y inside plot

      const xISO = pxToXISO(gd, px);
      const worker = pyToWorker(gd, py);

      if (xISO && worker) {
        host.dispatchEvent(new CustomEvent('gantt-dnd-drop', {
          detail: { taskId, dropWorkerName: worker, dropXISO: xISO },
          bubbles: true
        }));
      }
      dragging = null;
    });
  }

  function boot() {
    install();
    const mo = new MutationObserver(() => install());
    mo.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
