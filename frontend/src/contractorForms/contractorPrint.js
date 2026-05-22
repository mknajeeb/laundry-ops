/** Open a clean print window so only the form prints (no app sidebar/chrome). */

import printCss from "./contractorPrint.css?raw";

function waitForImages(doc) {
  const imgs = Array.from(doc.images || []);
  if (!imgs.length) return Promise.resolve();
  return Promise.all(
    imgs.map(
      (img) =>
        new Promise((resolve) => {
          if (img.complete) resolve();
          else {
            img.onload = () => resolve();
            img.onerror = () => resolve();
          }
        }),
    ),
  );
}

export function openPrintWindow(rootEl) {
  if (!rootEl) {
    window.print();
    return;
  }
  const win = window.open("", "_blank");
  if (!win) {
    printInPlace(rootEl);
    return;
  }
  const html = rootEl.innerHTML;
  win.document.open();
  win.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Print</title>
<style>${printCss}</style>
<style>
  @page { size: letter portrait; margin: 0.5in; }
  html, body {
    margin: 0;
    padding: 0;
    background: #fff !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  body { padding: 0.25in; }
</style>
</head>
<body class="contractor-print-body">
${html}
</body>
</html>`);
  win.document.close();
  const runPrint = () => {
    win.focus();
    win.print();
    win.onafterprint = () => win.close();
  };
  waitForImages(win.document).then(() => {
    setTimeout(runPrint, 150);
  });
}

/** Fallback when pop-up is blocked: hide app chrome via print CSS. */
function printInPlace(rootEl) {
  rootEl.classList.add("contractor-print-area--active");
  const cleanup = () => rootEl.classList.remove("contractor-print-area--active");
  window.addEventListener("afterprint", cleanup, { once: true });
  window.print();
}
