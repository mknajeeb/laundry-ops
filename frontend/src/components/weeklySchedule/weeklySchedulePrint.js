/** Open a clean print window for weekly schedule (avoids blank print from app shell / visibility rules). */

import weeklySchedulePrintDocumentCss from "./weeklySchedulePrintDocument.css?raw";

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

export function openWeeklySchedulePrintWindow(rootEl, { pageSize = "landscape" } = {}) {
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
<title>Weekly Schedule</title>
<style>${weeklySchedulePrintDocumentCss}</style>
<style>
  @page { size: ${pageSize}; margin: 10mm 8mm; }
  html, body {
    margin: 0;
    padding: 0;
    background: #fff !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
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

function printInPlace(rootEl) {
  document.body.classList.add("weekly-schedule-print-active");
  rootEl.classList.add("weekly-schedule-print-document--active");
  const cleanup = () => {
    document.body.classList.remove("weekly-schedule-print-active");
    rootEl.classList.remove("weekly-schedule-print-document--active");
  };
  window.addEventListener("afterprint", cleanup, { once: true });
  requestAnimationFrame(() => {
    setTimeout(() => window.print(), 100);
  });
}
