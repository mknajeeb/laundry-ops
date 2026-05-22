/** Open a clean print window so multi-page forms print/save as PDF correctly. */

export function openPrintWindow(rootEl) {
  if (!rootEl) {
    window.print();
    return;
  }
  const win = window.open("", "_blank", "noopener,noreferrer");
  if (!win) {
    window.print();
    return;
  }
  const headLinks = Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
    .map((el) => el.outerHTML)
    .join("\n");
  const inlineStyles = Array.from(document.querySelectorAll("style"))
    .map((el) => el.outerHTML)
    .join("\n");
  win.document.open();
  win.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Print</title>
${headLinks}
${inlineStyles}
<style>
  @page { size: letter portrait; margin: 0.5in; }
  html, body { margin: 0; padding: 0; background: #fff; }
</style>
</head>
<body class="contractor-print-body">
${rootEl.innerHTML}
</body>
</html>`);
  win.document.close();
  win.onload = () => {
    win.focus();
    setTimeout(() => {
      win.print();
      win.close();
    }, 400);
  };
  if (win.document.readyState === "complete") {
    win.onload();
  }
}
