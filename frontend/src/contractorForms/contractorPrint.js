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
  const margin = String(pageSize).toLowerCase().startsWith("a4") ? "12mm" : "0.4in";
  const bodyPad = String(pageSize).toLowerCase().startsWith("a4") ? "0" : "0.15in";
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
      waitForImages(doc).then(() => resolve({ iframe, doc, win: iframe.contentWindow }));
    };
    iframe.onerror = () => {
      iframe.remove();
      reject(new Error("Print iframe failed to load"));
    };
    document.body.appendChild(iframe);
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    iframe.src = url;
    iframe.dataset.blobUrl = url;
  });
}

/** Standalone document in a new window — avoids parent app CSS breaking html2canvas. */
function loadIsolatedHtmlWindow(html) {
  return new Promise((resolve, reject) => {
    const win = window.open("", "_blank", "noopener,noreferrer,width=920,height=1100");
    if (!win) {
      reject(new Error("Pop-up blocked — allow pop-ups for this site to download PDF"));
      return;
    }
    try {
      win.moveTo(-10000, 0);
      win.resizeTo(920, 1100);
    } catch {
      /* ignore */
    }
    win.document.open();
    win.document.write(html);
    win.document.close();
    waitForImages(win.document).then(() => {
      setTimeout(() => resolve({ win, doc: win.document }), 200);
    });
  });
}

async function loadHtmlForPdfCapture(html) {
  try {
    return await loadIsolatedHtmlWindow(html);
  } catch {
    const loaded = await loadPrintDocumentIframe(html);
    return { win: loaded.win, doc: loaded.doc, iframe: loaded.iframe };
  }
}

function cleanupPdfCaptureSession(session) {
  if (!session) return;
  if (session.iframe) {
    const url = session.iframe.dataset?.blobUrl;
    session.iframe.remove();
    if (url) URL.revokeObjectURL(url);
    return;
  }
  if (session.win) {
    try {
      session.win.close();
    } catch {
      /* ignore */
    }
  }
}

function pdfFormatFromPageSize(pageSize) {
  const size = String(pageSize || "letter portrait").toLowerCase();
  if (size.startsWith("a4")) return { format: "a4", orientation: "portrait" };
  if (size.includes("landscape")) return { format: "letter", orientation: "landscape" };
  return { format: "letter", orientation: "portrait" };
}

/** html2canvas chokes on @page, gradients, and some modern CSS — strip before capture. */
function sanitizeDocumentForPdfCapture(doc) {
  if (!doc) return;
  doc.querySelectorAll("style").forEach((node) => {
    node.textContent = node.textContent
      .replace(/@page\s*\{[^}]*\}/gi, "")
      .replace(/linear-gradient\([^;)]+\)/gi, "#f0fdfa")
      .replace(/font-variant-numeric\s*:[^;]+;?/gi, "")
      .replace(/object-fit\s*:[^;]+;?/gi, "")
      .replace(/-webkit-print-color-adjust\s*:[^;]+;?/gi, "")
      .replace(/print-color-adjust\s*:[^;]+;?/gi, "");
  });
  doc.querySelectorAll(".brand-head").forEach((el) => {
    el.style.background = "#f0fdfa";
  });
  doc.querySelectorAll("img.paystub-logo, img.vw-logo, img[class*='logo']").forEach((img) => {
    img.style.height = img.style.height || "44px";
    img.style.width = "auto";
    img.style.display = "block";
  });
}

async function captureElementToCanvas(element, { pageSize = "letter portrait", win } = {}) {
  const doc = element?.ownerDocument;
  if (doc) sanitizeDocumentForPdfCapture(doc);

  const [{ default: html2canvas }] = await Promise.all([import("html2canvas")]);

  return html2canvas(element, {
    scale: 2,
    backgroundColor: "#ffffff",
    logging: false,
    useCORS: true,
    allowTaint: true,
    foreignObjectRendering: false,
    windowWidth: win?.innerWidth || doc?.documentElement?.scrollWidth || 816,
    windowHeight: win?.innerHeight || doc?.documentElement?.scrollHeight || 1056,
    onclone: (clonedDoc) => sanitizeDocumentForPdfCapture(clonedDoc),
  });
}

function pdfCaptureTargets(doc) {
  const sheets = Array.from(doc.querySelectorAll(".paystub-sheet"));
  return sheets.length ? sheets : [doc.body];
}

async function renderBodyToPdf(body, { pageSize = "letter portrait", win } = {}) {
  const [{ default: jsPDF }] = await Promise.all([import("jspdf")]);

  const doc = body?.ownerDocument;
  const targets = doc ? pdfCaptureTargets(doc) : [body];
  const { format, orientation } = pdfFormatFromPageSize(pageSize);
  const pdf = new jsPDF({ orientation, unit: "in", format });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();

  for (let i = 0; i < targets.length; i += 1) {
    let canvas;
    try {
      canvas = await captureElementToCanvas(targets[i], { pageSize, win });
    } catch (firstErr) {
      if (doc) {
        doc.querySelectorAll("style").forEach((node) => node.remove());
      }
      try {
        canvas = await captureElementToCanvas(targets[i], { pageSize, win });
      } catch {
        throw firstErr;
      }
    }
    const imgData = canvas.toDataURL("image/jpeg", 0.92);
    let drawW = pageW;
    let drawH = (canvas.height * drawW) / canvas.width;
    if (drawH > pageH) {
      drawH = pageH;
      drawW = (canvas.width * drawH) / canvas.height;
    }
    const x = (pageW - drawW) / 2;
    if (i > 0) pdf.addPage();
    pdf.addImage(imgData, "JPEG", x, 0, drawW, drawH);
  }
  return pdf;
}

/** Download print-ready PDF (does not open the print dialog). */
export async function downloadPrintDocumentPdf(
  rootEl,
  { pageSize = "letter portrait", filename = "document.pdf", title = "Document" } = {},
) {
  const html = buildPrintDocumentHtml(rootEl, { pageSize, title });
  if (!html) return false;
  return downloadHtmlDocumentPdf(html, { pageSize, filename });
}

/** Download a full HTML document string as PDF (e.g. server-generated paystubs). */
export async function downloadHtmlDocumentPdf(
  html,
  { pageSize = "letter portrait", filename = "document.pdf" } = {},
) {
  const docHtml = absolutizePrintAssetUrls(html);
  if (!docHtml) return false;

  let session;
  try {
    session = await loadHtmlForPdfCapture(docHtml);
    const pdf = await renderBodyToPdf(session.doc.body, {
      pageSize,
      win: session.win,
    });
    pdf.save(filename);
    return true;
  } finally {
    cleanupPdfCaptureSession(session);
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
