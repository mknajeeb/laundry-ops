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

const PDF_CAPTURE_ROOT_CLASS = "paystub-pdf-capture-root";

function loadHtmlForPdfCapture(html) {
  return new Promise((resolve, reject) => {
    try {
      const container = document.createElement("div");
      container.className = PDF_CAPTURE_ROOT_CLASS;
      container.setAttribute("aria-hidden", "true");
      container.style.cssText =
        "position:fixed;left:0;top:0;width:816px;opacity:0;pointer-events:none;z-index:-1;overflow:hidden;background:#fff;";

      const parsed = new DOMParser().parseFromString(html, "text/html");
      parsed.querySelectorAll("style").forEach((styleEl) => {
        container.appendChild(styleEl.cloneNode(true));
      });
      Array.from(parsed.body.childNodes).forEach((node) => {
        container.appendChild(node.cloneNode(true));
      });

      document.body.appendChild(container);
      waitForImages(container).then(() => {
        setTimeout(() => resolve({ container, doc: document, win: window }), 150);
      });
    } catch (err) {
      reject(err);
    }
  });
}

function cleanupPdfCaptureSession(session) {
  if (session?.container) {
    session.container.remove();
  }
}

function stripNonCaptureStylesFromClone(clonedDoc) {
  if (!clonedDoc) return;
  clonedDoc.querySelectorAll("style, link[rel='stylesheet']").forEach((node) => {
    if (!node.closest(`.${PDF_CAPTURE_ROOT_CLASS}`)) {
      node.remove();
    }
  });
  const captureRoot = clonedDoc.querySelector(`.${PDF_CAPTURE_ROOT_CLASS}`);
  if (captureRoot) {
    sanitizePaystubStyles(captureRoot);
  }
}

function pdfFormatFromPageSize(pageSize) {
  const size = String(pageSize || "letter portrait").toLowerCase();
  if (size.startsWith("a4")) return { format: "a4", orientation: "portrait" };
  if (size.includes("landscape")) return { format: "letter", orientation: "landscape" };
  return { format: "letter", orientation: "portrait" };
}

/** html2canvas chokes on @page, gradients, and some modern CSS — strip before capture. */
function sanitizePaystubStyles(root) {
  if (!root) return;
  root.querySelectorAll("style").forEach((node) => {
    node.textContent = node.textContent
      .replace(/@page\s*\{[^}]*\}/gi, "")
      .replace(/linear-gradient\([^;)]+\)/gi, "#f0fdfa")
      .replace(/font-variant-numeric\s*:[^;]+;?/gi, "")
      .replace(/object-fit\s*:[^;]+;?/gi, "")
      .replace(/-webkit-print-color-adjust\s*:[^;]+;?/gi, "")
      .replace(/print-color-adjust\s*:[^;]+;?/gi, "");
  });
  root.querySelectorAll(".brand-head").forEach((el) => {
    el.style.background = "#f0fdfa";
  });
  root.querySelectorAll("img.paystub-logo, img.vw-logo, img[class*='logo']").forEach((img) => {
    img.style.height = img.style.height || "44px";
    img.style.width = "auto";
    img.style.display = "block";
  });
}

async function captureElementToCanvas(element, { pageSize = "letter portrait", win } = {}) {
  const captureRoot =
    element?.closest(`.${PDF_CAPTURE_ROOT_CLASS}`) ||
    (element?.classList?.contains(PDF_CAPTURE_ROOT_CLASS) ? element : null);
  if (captureRoot) {
    sanitizePaystubStyles(captureRoot);
  }

  const [{ default: html2canvas }] = await Promise.all([import("html2canvas")]);
  const w = Math.max(Math.ceil(element.scrollWidth || 0), 816);
  const h = Math.max(Math.ceil(element.scrollHeight || 0), 200);

  return html2canvas(element, {
    scale: 2,
    backgroundColor: "#ffffff",
    logging: false,
    useCORS: true,
    allowTaint: true,
    foreignObjectRendering: false,
    width: w,
    height: h,
    windowWidth: win?.innerWidth || w,
    windowHeight: win?.innerHeight || h,
    onclone: (clonedDoc) => stripNonCaptureStylesFromClone(clonedDoc),
  });
}

function pdfCaptureTargets(root) {
  const sheets = Array.from(root.querySelectorAll(".paystub-sheet"));
  return sheets.length ? sheets : [root];
}

async function renderBodyToPdf(root, { pageSize = "letter portrait", win } = {}) {
  const [{ default: jsPDF }] = await Promise.all([import("jspdf")]);

  const doc = root?.ownerDocument;
  const targets = root ? pdfCaptureTargets(root) : [root];
  const { format, orientation } = pdfFormatFromPageSize(pageSize);
  const pdf = new jsPDF({ orientation, unit: "in", format });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();

  for (let i = 0; i < targets.length; i += 1) {
    let canvas;
    try {
      canvas = await captureElementToCanvas(targets[i], { pageSize, win });
    } catch (firstErr) {
      if (root) {
        root.querySelectorAll("style").forEach((node) => node.remove());
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
    const pdf = await renderBodyToPdf(session.container, {
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
