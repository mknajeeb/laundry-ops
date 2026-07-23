/**
 * Distinct role choice colors so Operator / Folder (etc.) are not identical solid blues.
 * Returns MUI Button sx for outlined role options.
 */
export function roleChoiceButtonSx(roleName) {
  const n = String(roleName || "")
    .trim()
    .toLowerCase();

  if (n.includes("folder") || n.includes("fold")) {
    return {
      borderWidth: 2,
      borderColor: "#9a7209",
      color: "#7a5a08",
      bgcolor: "rgba(212, 168, 75, 0.16)",
      "&:hover": {
        borderWidth: 2,
        borderColor: "#9a7209",
        bgcolor: "rgba(212, 168, 75, 0.28)",
      },
    };
  }

  if (n.includes("operator") || n.includes("oper")) {
    return {
      borderWidth: 2,
      borderColor: "#4865ee",
      color: "#2d3d9c",
      bgcolor: "rgba(72, 101, 238, 0.12)",
      "&:hover": {
        borderWidth: 2,
        borderColor: "#2d3d9c",
        bgcolor: "rgba(72, 101, 238, 0.22)",
      },
    };
  }

  // Other roles: teal so they stay visually separate from Operator/Folder.
  return {
    borderWidth: 2,
    borderColor: "#0f766e",
    color: "#0f766e",
    bgcolor: "rgba(15, 118, 110, 0.1)",
    "&:hover": {
      borderWidth: 2,
      borderColor: "#0f766e",
      bgcolor: "rgba(15, 118, 110, 0.2)",
    },
  };
}
