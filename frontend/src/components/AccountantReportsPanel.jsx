import { useEffect, useState } from "react";
import { Stack, Tab, Tabs } from "@mui/material";
import AccountantW2DocumentsPanel from "../components/AccountantW2DocumentsPanel";
import AccountantW2PayrollPanel from "../components/AccountantW2PayrollPanel";

export default function AccountantReportsPanel({ initialSubTab = 0 }) {
  const [subTab, setSubTab] = useState(initialSubTab);

  useEffect(() => {
    setSubTab(initialSubTab);
  }, [initialSubTab]);

  return (
    <Stack spacing={2} sx={{ width: "100%", minWidth: 0 }}>
      <Tabs value={subTab} onChange={(_, v) => setSubTab(v)}>
        <Tab label="W-2 Payroll" />
        <Tab label="Documents" />
      </Tabs>

      {subTab === 0 ? <AccountantW2PayrollPanel /> : null}
      {subTab === 1 ? <AccountantW2DocumentsPanel /> : null}
    </Stack>
  );
}
