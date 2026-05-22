import { useEffect, useRef } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import PrintIcon from "@mui/icons-material/Print";
import { openPrintWindow } from "./contractorPrint";

/** On-screen print preview with a direct Print action. */
export default function ContractorPrintPreviewDialog({ open, onClose, title, printRef }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (open && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [open]);

  const handlePrint = () => {
    openPrintWindow(printRef?.current);
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{title || "Print preview"}</DialogTitle>
      <DialogContent dividers>
        <Box
          ref={scrollRef}
          sx={{
            bgcolor: "#f8fafc",
            p: 2,
            borderRadius: 1,
            maxHeight: "70vh",
            overflow: "auto",
          }}
        >
          <Box
            sx={{
              bgcolor: "#fff",
              boxShadow: 1,
              mx: "auto",
              width: "100%",
              maxWidth: "7.5in",
            }}
          >
            {printRef?.current ? (
              <Box dangerouslySetInnerHTML={{ __html: printRef.current.innerHTML }} />
            ) : (
              <Box sx={{ p: 2, color: "text.secondary" }}>Nothing to preview yet.</Box>
            )}
          </Box>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        <Button variant="contained" startIcon={<PrintIcon />} onClick={handlePrint}>
          Print
        </Button>
      </DialogActions>
    </Dialog>
  );
}
