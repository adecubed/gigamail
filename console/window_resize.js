// window_resize.js — the resize handle in the corner of the frameless
// windows. The page says which preload API resizes it and the minimum size
// on the <script> tag: data-api, data-min-w, data-min-h.
(function () {
  const cfg = document.currentScript ? document.currentScript.dataset : {};
  const minW = Number(cfg.minW) || 400;
  const minH = Number(cfg.minH) || 400;
  const handle = document.getElementById('resizeHandle');
  if (!handle) return;
  let startX, startY, startW, startH, dragging = false;
  handle.addEventListener('mousedown', (e) => {
    dragging = true; startX = e.screenX; startY = e.screenY;
    startW = window.outerWidth; startH = window.outerHeight; e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const w = Math.max(minW, startW + (e.screenX - startX));
    const h = Math.max(minH, startH + (e.screenY - startY));
    const api = window[cfg.api];
    if (api && api.resizeTo) api.resizeTo(Math.round(w), Math.round(h));
  });
  document.addEventListener('mouseup', () => { dragging = false; });
})();
