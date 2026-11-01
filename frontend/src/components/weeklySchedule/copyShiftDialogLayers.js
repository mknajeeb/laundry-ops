/** Copy Shift sits above schedule tooltips. Its employee menu is portaled to document.body. */

export function copyShiftDialogZIndex(theme) {
  return theme.zIndex.tooltip + 10;
}

/** One step above the dialog. The menu's default layer is modal, which is underneath this dialog. */
export function copyShiftEmployeeMenuZIndex(theme) {
  return copyShiftDialogZIndex(theme) + 10;
}
