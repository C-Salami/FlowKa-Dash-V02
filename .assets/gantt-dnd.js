// Drag & drop directly on the Plotly Gantt bars.
// We detect dragging on <rect> nodes, find their curve/point indices,
// resolve TaskId via customdata, compute the drop X (as ISO time) and drop Y (worker name),
// then dispatch a CustomEvent("gantt-dnd-drop", { detail: { taskId, dropWorkerName, dropXISO } }).

(function() {
  function findGraphDiv() {
    return document.querySelector('div.js-plotly-plot');
  }

  function pxToXISO(gd, px) {
    // convert pixel (relative to plot area) to x (date) then to ISO
    try {
      const xa = gd._fullLayout.xaxis;
      const xVal = xa.p2l ? xa.p2l(px) : xa.p2d(px); // p2l for pixel->linear
      // plotly stores ms since epoch for dates; normalize to Date
      const dt = new Date(xVal);
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
      // choose the category whose pixel position is closest to py
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
    // Plotly attaches data-curvenumber and data-pointnumber to bar nodes.
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
    if (!gd || gd._ganttDndInstalled) return;
    gd._ganttDndInstalled = true;

    let dragging = null;

    gd.addEventListener('mousedown', function(e) {
      const t = e.target;
      if (!(t && t.tagName === 'rect' && t.hasAttribute('data-pointnumber'))) return;

      const taskId = resolveTaskIdFromNode(gd, t);
      if (!taskId) return;

      const plotArea = gd.querySelector('.cartesianlayer .plot');
      if (!plotArea) return;

      // get plot area bounding box to compute local px/py
      const plotBox = plotArea.getBoundingClientRect();

      dragging = { taskId, startX: e.clientX, startY: e.clientY, plotBox };
      e.preventDefault();
    }, true);

    window.addEventListener('mousemove', function(e) {
      if (!dragging) return;
      // could draw a ghost; keeping it simple
    });

    window.addEventListener('mouseup', function(e) {
      if (!dragging) return;
      const gd = findGraphDiv();
      const plotArea = gd && gd.querySelector('.cartesianlayer .plot');
      if (!gd || !plotArea) { dragging = null; return; }

      const { plotBox, taskId } = dragging;
      const px = e.clientX - plotBox.left; // x inside plot
      const py = e.clientY - plotBox.top;  // y inside plot

      // convert to axis values
      const xISO = pxToXISO(gd, px);
      const worker = pyToWorker(gd, py);

      if (xISO && worker) {
        const ev = new CustomEvent('gantt-dnd-drop', {
          detail: { taskId: taskId, dropWorkerName: worker, dropXISO: xISO },
          bubbles: true
        });
        document.dispatchEvent(ev);
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
