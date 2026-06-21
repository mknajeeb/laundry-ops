import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  InputLabel,
  Link,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import {
  deleteTaUserDocument,
  getContractors,
  getTaUserDocuments,
  getTaUsers,
  postTaUserDocument,
  putTaUserDocument,
} from "../api";
import { IRS_W9_URL } from "../contractorForms/contractorDocumentChecklist";
import {
  checklistForWorkerCategory,
  WORKER_CATEGORY_OPTIONS,
} from "../payroll/payrollDocumentChecklists";

export default function PayrollDocumentsPanel({ category: categoryProp, workerLabel: workerLabelProp }) {
  const [category, setCategory] = useState(categoryProp || "w2");
  const [selected, setSelected] = useState(null);
  const [records, setRecords] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [error, setError] = useState("");

  const checklist = checklistForWorkerCategory(category);
  const lockedCategory = Boolean(categoryProp);
  const workerFieldLabel =
    workerLabelProp ||
    (category === "contractor_1099" ? "1099 contractor" : category === "temp" ? "Temp worker" : "W-2 employee");
  useEffect(() => {
    if (categoryProp) setCategory(categoryProp);
  }, [categoryProp]);

  const loadWorkers = useCallback(async () => {
    try {
      if (category === "contractor_1099" || category === "temp") {
        const res = await getContractors();
        const list = (res.data?.contractors || []).filter((c) => {
          if (category === "temp") return c.worker_kind === "short_term" || c.worker_kind === "1099_and_temp";
          return c.worker_kind === "1099" || c.worker_kind === "1099_and_temp";
        });
        setWorkers(list.map((c) => ({ id: c.user_id, label: c.full_name })));
      } else {
        const res = await getTaUsers();
        const list = (res.data?.users || res.data || []).map((u) => ({
          id: u.id,
          label: `${u.first_name || ""} ${u.last_name || ""}`.trim(),
        }));
        setWorkers(list);
      }
    } catch {
      setWorkers([]);
    }
  }, [category]);

  const loadDocs = useCallback(async () => {
    if (!selected?.id) {
      setRecords([]);
      return;
    }
    try {
      const res = await getTaUserDocuments(selected.id);
      setRecords(res.data?.items || res.data || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Load failed");
    }
  }, [selected?.id]);

  useEffect(() => {
    loadWorkers();
    setSelected(null);
  }, [loadWorkers]);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const recordFor = (code) => records.find((r) => String(r.document_code) === code);

  const upsert = async (code, name, patch) => {
    if (!selected?.id) return;
    const ex = recordFor(code);
    try {
      if (ex?.id) {
        await putTaUserDocument(selected.id, ex.id, { ...ex, ...patch });
      } else {
        await postTaUserDocument(selected.id, {
          document_code: code,
          document_name: name,
          status: patch.status || "received",
          file_uri: patch.file_uri || "",
          notes: patch.notes || "",
          source_kind: "uploaded",
        });
      }
      await loadDocs();
    } catch (e) {
      setError(e.response?.data?.error || "Save failed");
    }
  };

  const remove = async (code) => {
    const ex = recordFor(code);
    if (!ex?.id || !window.confirm("Delete document record?")) return;
    try {
      await deleteTaUserDocument(selected.id, ex.id);
      await loadDocs();
    } catch (e) {
      setError(e.response?.data?.error || "Delete failed");
    }
  };

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      <Paper sx={{ p: 2 }}>
        {!lockedCategory ? (
          <>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Documents
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Grouped by worker category. Upload signed copies (paste file URL). Old C-document
              compliance is not used here.
            </Typography>
          </>
        ) : null}
        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          {!lockedCategory ? (
            <FormControl size="small" sx={{ minWidth: 200 }}>
              <InputLabel>Worker category</InputLabel>
              <Select
                label="Worker category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {WORKER_CATEGORY_OPTIONS.filter((o) => o.value !== "all").map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : null}
          <Autocomplete
            sx={{ minWidth: 280, flex: 1 }}
            options={workers}
            value={selected}
            onChange={(_, v) => setSelected(v)}
            getOptionLabel={(o) => o?.label || ""}
            renderInput={(params) => (
              <TextField {...params} label={`Select ${workerFieldLabel}`} size="small" />
            )}
          />
        </Stack>
      </Paper>

      {selected ? (
        <Table size="small" component={Paper}>
          <TableHead>
            <TableRow>
              <TableCell>Document</TableCell>
              <TableCell width={80}>Received</TableCell>
              <TableCell>File URL</TableCell>
              <TableCell>Notes</TableCell>
              <TableCell width={140}>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {checklist.map((item) => {
              const rec = recordFor(item.code);
              const ok = rec?.file_uri || rec?.status === "received" || rec?.status === "verified";
              return (
                <TableRow key={item.code}>
                  <TableCell>
                    {item.name}
                    {item.required ? " *" : ""}
                    {item.code === "contractor_w9" || item.code === "w2_w4" ? (
                      <Box>
                        <Link href={IRS_W9_URL} target="_blank" rel="noreferrer" sx={{ fontSize: 12 }}>
                          IRS form <OpenInNewIcon sx={{ fontSize: 12 }} />
                        </Link>
                      </Box>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <FormControlLabel
                      control={
                        <Checkbox
                          size="small"
                          checked={!!ok}
                          onChange={(e) =>
                            upsert(item.code, item.name, {
                              status: e.target.checked ? "received" : "pending",
                              file_uri: rec?.file_uri || "",
                            })
                          }
                        />
                      }
                      label=""
                    />
                  </TableCell>
                  <TableCell>
                    <TextField
                      size="small"
                      fullWidth
                      value={rec?.file_uri || ""}
                      onChange={(e) =>
                        upsert(item.code, item.name, {
                          status: "received",
                          file_uri: e.target.value,
                          notes: rec?.notes || "",
                        })
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <TextField
                      size="small"
                      fullWidth
                      value={rec?.notes || ""}
                      onChange={(e) =>
                        upsert(item.code, item.name, {
                          file_uri: rec?.file_uri || "",
                          notes: e.target.value,
                          status: rec?.status || "received",
                        })
                      }
                    />
                  </TableCell>
                  <TableCell>
                    {rec?.file_uri ? (
                      <Button size="small" href={rec.file_uri} target="_blank">
                        View
                      </Button>
                    ) : null}
                    {rec?.id ? (
                      <Button size="small" color="error" onClick={() => remove(item.code)}>
                        Delete
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      ) : (
        <Alert severity="info">Select a worker to manage documents.</Alert>
      )}
    </Stack>
  );
}
