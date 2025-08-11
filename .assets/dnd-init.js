// Initializes SortableJS on any element with class "dnd-list".
// Dispatches CustomEvent("dnd", { detail: { itemId, fromId, toId, newIndex } }) on drop.

(function() {
  function ensureSortable(callback) {
    if (window.Sortable) { callback(); return; }
    var s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js';
    s.onload = callback;
    document.head.appendChild(s);
  }

  function initList(el) {
    if (!el || el._sortable_inited) return;
    el._sortable_inited = true;
    Sortable.create(el, {
      group: 'tasks',
      animation: 150,
      fallbackOnBody: true,
      swapThreshold: 0.65,
      onEnd: function(evt) {
        try {
          var itemEl = evt.item;
          var itemId = itemEl.getAttribute('data-task-id');
          var fromId = evt.from.getAttribute('data-list-id');
          var toId   = evt.to.getAttribute('data-list-id');
          var newIndex = evt.newIndex;
          document.dispatchEvent(new CustomEvent('dnd', { detail: { itemId, fromId, toId, newIndex }, bubbles: true }));
        } catch (e) {
          console.error('DnD dispatch error', e);
        }
      }
    });
  }

  function initAll() {
    var lists = document.querySelectorAll('.dnd-list');
    lists.forEach(initList);
  }

  ensureSortable(function() {
    initAll();
    var mo = new MutationObserver(function() { initAll(); });
    mo.observe(document.body, { childList: true, subtree: true });
  });
})();
