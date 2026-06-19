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

function printPageStyles(pageSize = "letter portrait") {
  const margin = String(pageSize).toLowerCase().startsWith("a4") ? "12mm" : "0.5in";
  const bodyPad = String(pageSize).toLowerCase().startsWith("a4") ? "0" : "0.25in";
  return { margin, bodyPad };
}

/** Build standalone HTML for print/download (same shell as openPrintWindow, no print dialog). */
export function buildPrintDocumentHtml(
  rootEl,
  { pageSize = "letter portrait", title = "Document" } = {},
) {
  if (!rootEl) return "";
  const html = rootEl.innerHTML;
  const { margin, bodyPad } = printPageStyles(pageSize);
  const safeTitle = String(title || "Document").replace(/[<>&"]/g, "");
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>${safeTitle}</title>
<style>${printDocumentCss}</style>
<style>
  @page { size: ${pageSize}; margin: ${margin}; }
  html, body {
    margin: 0;
    padding: 0;
    background: #fff !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  body { padding: ${bodyPad}; }
</style>
</head>
<body>
${html}
</body>
</html>`;
}

/** Download print-ready HTML file (does not open the print dialog). */
export function downloadPrintDocument(
  rootEl,
  { pageSize = "letter portrait", filename = "document.html", title = "Document" } = {},
) {
  const doc = buildPrintDocumentHtml(rootEl, { pageSize, title });
  if (!doc) return false;
  const blob = new Blob([doc], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return true;
}

export function openPrintWindow(rootEl, { pageSize = "letter portrait" } = {}) {
  if (!rootEl) {
    window.print();
    return;
  }
  const html = rootEl.innerHTML;
  const { margin, bodyPad } = printPageStyles(pageSize);
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
  @page { size: ${pageSize}; margin: ${margin}; }
  html, body {
    margin: 0;
    padding: 0;
    background: #fff !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  body { padding: ${bodyPad}; }
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
