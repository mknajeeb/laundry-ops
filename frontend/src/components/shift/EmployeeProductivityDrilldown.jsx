import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Collapse,
  Link,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import ShiftBagRecordRow from "./ShiftBagRecordRow";

/** Phase 1 drilldown — chronological bag table + clickable bag expand (frozen attribution). */
export default function EmployeeProductivityDrilldown({
  bags,
  referenceDateEt,
  loading = false,
}) {
  const [expandedBagId, setExpandedBagId] = useState(null);

  const sortedBags = useMemo(
    () => [...(bags || [])].sort(
      (a, b) => String(a.completion_time || a.completion_timestamp || "")
        .localeCompare(String(b.completion_time || b.completion_timestamp || "")),
    ),
    [bags],
  );

  if (loading) {
    return (
      <Typography variant="body2" color="text.secondary">
        Loading bag details…
      </Typography>
    );
  }
  if (!sortedBags.length) {
    return (
      <Typography variant="body2" color="text.secondary">
        No completed bags for this employee.
      </Typography>
    );
  }

  const expandedBag = sortedBags.find((b) => b.bag_id === expandedBagId);

  return (
    <Box sx={{ py: 1.5 }}>
      <Table size="small" sx={{ mb: 1 }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ fontWeight: 700 }}>Completion Time</TableCell>
            <TableCell sx={{ fontWeight: 700 }}>Bag ID</TableCell>
            <TableCell sx={{ fontWeight: 700 }}>Customer</TableCell>
            <TableCell sx={{ fontWeight: 700 }}>Service Type</TableCell>
            <TableCell sx={{ fontWeight: 700 }} align="right">Weight</TableCell>
            <TableCell sx={{ fontWeight: 700 }}>Completion Signal</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {sortedBags.map((bag) => (
            <TableRow
              key={bag.bag_id}
              selected={expandedBagId === bag.bag_id}
              hover
            >
              <TableCell>{bag.completion_time_et || "—"}</TableCell>
              <TableCell>
                <Link
                  component="button"
                  type="button"
                  underline="hover"
                  fontWeight={700}
                  onClick={(e) => {
                    e.stopPropagation();
                    setExpandedBagId((prev) => (prev === bag.bag_id ? null : bag.bag_id));
                  }}
                >
                  {bag.bag_id}
                </Link>
              </TableCell>
              <TableCell>{bag.customer_name || "—"}</TableCell>
              <TableCell>{bag.service_type || bag.service_bucket || "—"}</TableCell>
              <TableCell align="right">
                {bag.completed_lbs != null ? `${bag.completed_lbs} lbs` : "—"}
              </TableCell>
              <TableCell>{bag.completion_signal || "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {expandedBag ? (
        <ShiftBagRecordRow
          key={expandedBag.bag_id}
          row={expandedBag}
          variant="at_vendor"
          referenceDateEt={referenceDateEt}
          defaultOpen
        />
      ) : null}
    </Box>
  );
}

export function EmployeeProductivityDrilldownCollapse({ open, children }) {
  return (
    <Collapse in={open} unmountOnExit>
      {children}
    </Collapse>
  );
}
