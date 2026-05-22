import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  Link,
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
  getTaUserDocuments,
  postTaUserDocument,
  putTaUserDocument,
} from "../api";
import {
  checklistForType,
  IRS_W9_URL,
} from "../contractorForms/contractorDocumentChecklist";

export default function ContractorDocumentsPanel({
  userId,
  contractorType = "regular",
  ytdTotal = 0,
}) {
  const [records, setRecords] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const checklist = checklistForType(contractorType);

  const load = useCallback(async () => {
    if (!userId) {
      setRecords([]);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await getTaUserDocuments(userId);
      setRecords(res.data?.items || res.data || []);
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  const recordForCode = (code) =>
    (records || []).find((r) => String(r.document_code) === code);

  const upsertDoc = async (code, name, patch) => {
    if (!userId) return;
    const existing = recordForCode(code);
    try {
      if (existing?.id) {
        await putTaUserDocument(userId, existing.id, { ...existing, ...patch });
      } else {
        await postTaUserDocument(userId, {
          document_code: code,
          document_name: name,
          status: patch.status || "received",
          file_uri: patch.file_uri || "",
          notes: patch.notes || "",
          source_kind: "uploaded",
        });
      }
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Document save failed");
    }
  };

  const removeDoc = async (code) => {
    const existing = recordForCode(code);
    if (!existing?.id || !userId) return;
    if (!window.confirm("Delete this document record?")) return;
    try {
      await deleteTaUserDocument(userId, existing.id);
      await load();
    } catch (e) {
      setError(e.response?.data?.error || e.message || "Delete failed");
    }
  };

  if (!userId) {
    return (
      <Alert severity="info">
        Select a contractor with a Laundry Ops profile to manage W-9 and signed documents.
        Temp/one-time workers without a profile can still print and save payment records on the
        Invoice &amp; Payment Receipt tab.
      </Alert>
    );
  }

  const showW9Warning =
    contractorType !== "regular" && ytdTotal >= 600;

  return (
    <Stack spacing={2}>
      {error ? (
        <Alert severity="error" onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}
      {showW9Warning ? (
        <Alert severity="warning">
          Year-to-date payments are ${ytdTotal.toFixed(2)}. Review W-9 / 1099 requirement before
          additional payments.
        </Alert>
      ) : null}
      <Typography variant="body2" color="text.secondary">
        Upload signed copies (paste a file link URL). Generated forms are printed from Forms
        &amp; Packets.
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Document</TableCell>
            <TableCell width={90}>Received</TableCell>
            <TableCell>File link</TableCell>
            <TableCell>Notes</TableCell>
            <TableCell width={200}>Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {checklist.map((item) => {
            const rec = recordForCode(item.code);
            const received = rec?.status === "received" || rec?.status === "verified" || !!rec?.file_uri;
            return (
              <TableRow key={item.code}>
                <TableCell>
                  <Typography variant="body2">
                    {item.name}
                    {item.required ? " *" : ""}
                  </Typography>
                  {item.code === "contractor_w9" ? (
                    <Link href={IRS_W9_URL} target="_blank" rel="noreferrer" sx={{ fontSize: 12 }}>
                      Open IRS W-9 <OpenInNewIcon sx={{ fontSize: 12 }} />
                    </Link>
                  ) : null}
                </TableCell>
                <TableCell>
                  <FormControlLabel
                    control={
                      <Checkbox
                        size="small"
                        checked={received}
                        onChange={(e) =>
                          upsertDoc(item.code, item.name, {
                            status: e.target.checked ? "received" : "pending",
                            file_uri: rec?.file_uri || "",
                            notes: rec?.notes || "",
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
                    placeholder="https://..."
                    value={rec?.file_uri || ""}
                    onChange={(e) =>
                      upsertDoc(item.code, item.name, {
                        status: rec?.status || "received",
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
                      upsertDoc(item.code, item.name, {
                        status: rec?.status || "received",
                        file_uri: rec?.file_uri || "",
                        notes: e.target.value,
                      })
                    }
                  />
                </TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.5}>
                    {rec?.file_uri ? (
                      <Button size="small" href={rec.file_uri} target="_blank" rel="noreferrer">
                        View
                      </Button>
                    ) : null}
                    {rec?.id ? (
                      <Button size="small" color="error" onClick={() => removeDoc(item.code)}>
                        Delete
                      </Button>
                    ) : null}
                  </Stack>
                  {rec?.created_at ? (
                    <Typography variant="caption" color="text.secondary" display="block">
                      {String(rec.created_at).slice(0, 10)}
                    </Typography>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {loading ? (
        <Typography variant="caption" color="text.secondary">
          Loading…
        </Typography>
      ) : null}
    </Stack>
  );
}
