import { useState } from "react";
import {
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import AccountantW2DocumentsPanel from "./AccountantW2DocumentsPanel";
import PayrollDocumentsPanel from "./PayrollDocumentsPanel";
import { PAYROLL_DOCUMENT_CATEGORY_OPTIONS } from "../payroll/payrollDocumentChecklists";

const WORKER_LABELS = {
  w2: "W-2 employee",
  contractor_1099: "1099 contractor",
  temp: "Temp worker",
};

/**
 * Payroll Documents for admins: W-2, 1099, and temp workers.
 * W-2 uses full accountant document tools; contractors/temps use category checklist.
 */
export default function PayrollWorkerDocumentsPanel() {
  const [category, setCategory] = useState("w2");

  return (
    <Stack spacing={2}>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 0.5 }}>
          Worker documents
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Manage signed handbook, tax, and compliance files by worker type. Accountants are limited to
          W-2 employees; admins can file documents for all payroll worker categories.
        </Typography>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel id="payroll-doc-category">Worker category</InputLabel>
          <Select
            labelId="payroll-doc-category"
            label="Worker category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {PAYROLL_DOCUMENT_CATEGORY_OPTIONS.map((o) => (
              <MenuItem key={o.value} value={o.value}>
                {o.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Paper>

      {category === "w2" ? (
        <AccountantW2DocumentsPanel embedded />
      ) : (
        <PayrollDocumentsPanel category={category} workerLabel={WORKER_LABELS[category]} />
      )}
    </Stack>
  );
}
