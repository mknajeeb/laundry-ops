import { useState } from "react";
import {
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import AccountantW2DocumentsPanel from "./AccountantW2DocumentsPanel";
import PayrollDocumentsPanel from "./PayrollDocumentsPanel";
import PayrollHrTimelinePanel from "./PayrollHrTimelinePanel";
import { PAYROLL_DOCUMENT_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

const WORKER_LABELS = {
  w2: "W-2 employee",
  contractor_1099: "1099 contractor",
  temp: "Temp worker",
};

/**
 * Payroll Documents + HR Timeline for admins: W-2, 1099, and temp workers.
 */
export default function PayrollWorkerDocumentsPanel() {
  const [category, setCategory] = useState("w2");
  const [sectionTab, setSectionTab] = useState("documents");

  return (
    <Stack spacing={2}>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 0.5 }}>
          Worker documents & HR
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Signed handbook and compliance files, plus internal HR Timeline (coaching, warnings,
          separation notes). Accountants are limited to W-2 employees; admins can manage all payroll
          worker categories.
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
          <FormControl size="small" sx={{ minWidth: 220 }}>
            <InputLabel id="payroll-doc-category">Worker category</InputLabel>
            <Select
              labelId="payroll-doc-category"
              label="Worker category"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setSectionTab("documents");
              }}
            >
              {PAYROLL_DOCUMENT_CATEGORY_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Tabs
            value={sectionTab}
            onChange={(_, v) => setSectionTab(v)}
            sx={{ minHeight: 36 }}
          >
            <Tab value="documents" label="Signed documents" sx={{ minHeight: 36, py: 0.5 }} />
            <Tab value="hr_timeline" label="HR Timeline" sx={{ minHeight: 36, py: 0.5 }} />
          </Tabs>
        </Stack>
      </Paper>

      {sectionTab === "documents" ? (
        category === "w2" ? (
          <AccountantW2DocumentsPanel embedded />
        ) : (
          <PayrollDocumentsPanel category={category} workerLabel={WORKER_LABELS[category]} />
        )
      ) : (
        <PayrollHrTimelinePanel category={category} />
      )}
    </Stack>
  );
}
