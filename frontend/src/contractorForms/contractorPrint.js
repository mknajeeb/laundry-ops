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

/** Resolve root-relative asset URLs so print iframes and PDF capture can load images. */
export function absolutizePrintAssetUrls(html) {
  if (!html || typeof window === "undefined") return html;
  const origin = window.location.origin;
  return html.replace(/(\s(?:src|href)=["'])\/([^"']+)/g, `$1${origin}/$2`);
}

/** Build standalone HTML for print/download (same shell as openPrintWindow, no print dialog). */
export function buildPrintDocumentHtml(
  rootEl,
  { pageSize = "letter portrait", title = "Document" } = {},
) {
  if (!rootEl) return "";
  const html = absolutizePrintAssetUrls(rootEl.innerHTML);
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

function loadPrintDocumentIframe(html) {
  return new Promise((resolve, reject) => {
    const iframe = document.createElement("iframe");
    iframe.setAttribute("aria-hidden", "true");
    iframe.style.cssText =
      "position:fixed;left:-10000px;top:0;width:8.5in;height:11in;border:0;visibility:hidden;";
    iframe.onload = () => {
      const doc = iframe.contentDocument;
      if (!doc?.body) {
        iframe.remove();
        reject(new Error("Print iframe failed to load"));
        return;
      }
      waitForImages(doc).then(() => resolve({ iframe, doc }));
    };
    iframe.onerror = () => {
      iframe.remove();
      reject(new Error("Print iframe failed to load"));
    };
    document.body.appendChild(iframe);
    iframe.srcdoc = html;
  });
}

function pdfFormatFromPageSize(pageSize) {
  const size = String(pageSize || "letter portrait").toLowerCase();
  if (size.startsWith("a4")) return { format: "a4", orientation: "portrait" };
  if (size.includes("landscape")) return { format: "letter", orientation: "landscape" };
  return { format: "letter", orientation: "portrait" };
}

/** Download print-ready PDF (does not open the print dialog). */
export async function downloadPrintDocumentPdf(
  rootEl,
  { pageSize = "letter portrait", filename = "document.pdf", title = "Document" } = {},
) {
  const html = buildPrintDocumentHtml(rootEl, { pageSize, title });
  if (!html) return false;

  let iframe;
  try {
    const loaded = await loadPrintDocumentIframe(html);
    iframe = loaded.iframe;
    const body = loaded.doc.body;

    const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
      import("html2canvas"),
      import("jspdf"),
    ]);

    const canvas = await html2canvas(body, {
      scale: 2,
      backgroundColor: "#ffffff",
      logging: false,
      useCORS: true,
    });

    const { format, orientation } = pdfFormatFromPageSize(pageSize);
    const pdf = new jsPDF({ orientation, unit: "in", format });
    const pageW = pdf.internal.pageSize.getWidth();
    const pageH = pdf.internal.pageSize.getHeight();
    const imgData = canvas.toDataURL("image/jpeg", 0.95);
    const imgProps = pdf.getImageProperties(imgData);
    const imgW = pageW;
    const imgH = (imgProps.height * imgW) / imgProps.width;
    const y = imgH <= pageH ? 0 : 0;
    const drawH = imgH <= pageH ? imgH : pageH;
    const drawW = imgH <= pageH ? imgW : (imgProps.width * drawH) / imgProps.height;
    const x = imgH <= pageH ? 0 : (pageW - drawW) / 2;
    pdf.addImage(imgData, "JPEG", x, y, drawW, drawH);
    pdf.save(filename);
    return true;
  } finally {
    iframe?.remove();
  }
}

export function openPrintWindow(rootEl, { pageSize = "letter portrait" } = {}) {
  if (!rootEl) {
    window.print();
    return;
  }
  const html = absolutizePrintAssetUrls(rootEl.innerHTML);
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
