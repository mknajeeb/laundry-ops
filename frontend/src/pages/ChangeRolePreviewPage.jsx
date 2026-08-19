import { useMemo } from "react";
import { Box } from "@mui/material";
import { useSearchParams } from "react-router-dom";
import OpsSwitchRoleFlow from "../opsMobile/OpsSwitchRoleFlow";

const PREVIEW_ROLES = [
  { role_id: 1, role_name: "Operator" },
  { role_id: 3, role_name: "Sort" },
  { role_id: 2, role_name: "Folder" },
];

/** Local visual review of the role-first Change Role UI. Not for production use. */
const PREVIEW_TREE = [
  { id: 1, code: "rinse_wf", name: "Rinse WF", roles: PREVIEW_ROLES },
  { id: 2, code: "rinse_hd", name: "Rinse HD", roles: PREVIEW_ROLES },
  { id: 3, name: "DHS", roles: PREVIEW_ROLES },
  { id: 4, name: "Drop Off", roles: PREVIEW_ROLES },
];

export default function ChangeRolePreviewPage() {
  const [params] = useSearchParams();
  const view = params.get("view") || "collapsed";
  const expanded = useMemo(() => {
    if (view === "washdry") return "Wash-Dry";
    if (view === "fold") return "Fold";
    return null;
  }, [view]);

  return (
    <Box
      data-preview-phone
      sx={{
        width: 390,
        minHeight: "100dvh",
        mx: "auto",
        boxSizing: "border-box",
      }}
    >
      <OpsSwitchRoleFlow
        employeeName="Yesenia"
        selectionTree={PREVIEW_TREE}
        currentCategoryId={2}
        currentRoleId={2}
        defaultExpandedRole={expanded}
        onBack={() => {}}
        onLock={() => {}}
        onSelectCombo={() => {}}
      />
    </Box>
  );
}
