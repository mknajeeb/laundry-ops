/** Open a clean print window — document CSS only (avoids blank print from visibility:hidden). */

import printDocumentCss from "./contractorPrintDocument.css?raw";

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
  const html = rootEl.innerHTML;
  const win = window.open("", "_blank");
  if (!win) {
    printInPlace(rootEl);
    return;
  }
  win.document.open();
  win.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Print</title>
<style>${printDocumentCss}</style>
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
<body>
${html}
</body>
</html>`);
  win.document.close();

  const triggerPrint = () => {
    requestAnimationFrame(() => {
      waitForImages(win.document).then(() => {
        setTimeout(() => {
          win.focus();
          win.print();
          win.onafterprint = () => {
            try {
              win.close();
            } catch {
              /* ignore */
            }
          };
        }, 250);
      });
    });
  };

  if (win.document.readyState === "complete") {
    triggerPrint();
  } else {
    win.onload = triggerPrint;
  }
}

/** Fallback when pop-up is blocked. */
function printInPlace(rootEl) {
  rootEl.classList.add("contractor-print-area--active");
  const cleanup = () => rootEl.classList.remove("contractor-print-area--active");
  window.addEventListener("afterprint", cleanup, { once: true });
  requestAnimationFrame(() => {
    setTimeout(() => window.print(), 100);
  });
}
