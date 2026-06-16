import { useState } from "react";
import { Paper, Stack, Tab, Tabs, Typography } from "@mui/material";
import AccountantW2DocumentsPanel from "../components/AccountantW2DocumentsPanel";
import AccountantW2PayrollPanel from "../components/AccountantW2PayrollPanel";

/** Read-only accountant workspace: W-2 payroll summary + W-2 documents. */
export default function AccountantReportsPanel() {
  const [subTab, setSubTab] = useState(0);

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6">Accountant workspace</Typography>
        <Typography variant="body2" color="text.secondary">
          Review W-2 payroll by pay period, then open employee documents and direct deposit forms.
        </Typography>
      </Paper>

      <Tabs value={subTab} onChange={(_, v) => setSubTab(v)}>
        <Tab label="W-2 payroll" />
        <Tab label="W-2 documents" />
      </Tabs>

      {subTab === 0 ? <AccountantW2PayrollPanel /> : null}
      {subTab === 1 ? <AccountantW2DocumentsPanel /> : null}
    </Stack>
  );
}
