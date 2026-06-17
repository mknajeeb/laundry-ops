import { useMemo, useState } from "react";
import {
  Box,
  Collapse,
  Link,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import ShiftBagRecordRow from "./ShiftBagRecordRow";
import { formatIsoEtWall } from "../../utils/rinseTimeFormat";

function completionTs(bag) {
  return String(bag.completion_time || bag.completion_timestamp || "");
}

function BagMobileCard({ bag, expanded, onToggle, referenceDateEt }) {
  return (
    <Paper variant="outlined" sx={{ p: 1.1, borderRadius: 1.5 }}>
      <Stack spacing={0.5}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Box sx={{ minWidth: 0 }}>
            <Link
              component="button"
              type="button"
              underline="hover"
              fontWeight={800}
              onClick={(e) => {
                e.stopPropagation();
                onToggle();
              }}
              sx={{ fontSize: "0.95rem", wordBreak: "break-all", textAlign: "left" }}
            >
              {bag.bag_id}
            </Link>
            <Typography variant="body2" color="text.secondary">
              {formatIsoEtWall(bag.completion_time_et || bag.completion_time || bag.completion_timestamp)}
            </Typography>
          </Box>
          <Typography variant="body2" fontWeight={700} sx={{ whiteSpace: "nowrap" }}>
            {bag.completed_lbs != null ? `${bag.completed_lbs} lbs` : "—"}
          </Typography>
        </Stack>
        <Typography variant="body2" sx={{ wordBreak: "break-word" }}>
          {bag.customer_name || "—"}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {bag.service_type || bag.service_bucket || "—"} · {bag.completion_signal || "—"}
        </Typography>
      </Stack>
      <Collapse in={expanded} unmountOnExit>
        <Box sx={{ mt: 1 }}>
          <ShiftBagRecordRow
            row={bag}
            variant="at_vendor"
            referenceDateEt={referenceDateEt}
            defaultOpen
          />
        </Box>
      </Collapse>
    </Paper>
  );
}

/** Phase 1 drilldown — chronological bag table + clickable bag expand (frozen attribution). */
export default function EmployeeProductivityDrilldown({
  bags,
  referenceDateEt,
  loading = false,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [expandedBagId, setExpandedBagId] = useState(null);

  const sortedBags = useMemo(
    () => [...(bags || [])].sort((a, b) => completionTs(a).localeCompare(completionTs(b))),
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

  if (isMobile) {
    return (
      <Box sx={{ py: 0.5 }}>
        <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
          Completed Bags
        </Typography>
        <Stack spacing={1}>
          {sortedBags.map((bag) => (
            <BagMobileCard
              key={bag.bag_id}
              bag={bag}
              expanded={expandedBagId === bag.bag_id}
              onToggle={() => setExpandedBagId((prev) => (prev === bag.bag_id ? null : bag.bag_id))}
              referenceDateEt={referenceDateEt}
            />
          ))}
        </Stack>
      </Box>
    );
  }

  return (
    <Box sx={{ py: 0.5 }}>
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 0.75 }}>
        Completed Bags
      </Typography>
      <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 1.5, overflowX: "auto" }}>
        <Table size="small" aria-label="Employee completed bags drilldown">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Completion Time</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Bag ID</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Customer</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Service</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }} align="right">Weight</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1.1 }}>Completion Signal</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedBags.map((bag) => (
              <TableRow
                key={bag.bag_id}
                selected={expandedBagId === bag.bag_id}
                hover
                sx={{ "& td": { py: 1.1 } }}
              >
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  {formatIsoEtWall(bag.completion_time_et || bag.completion_time || bag.completion_timestamp)}
                </TableCell>
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
                <TableCell sx={{ maxWidth: 180, wordBreak: "break-word" }}>{bag.customer_name || "—"}</TableCell>
                <TableCell>{bag.service_type || bag.service_bucket || "—"}</TableCell>
                <TableCell align="right">
                  {bag.completed_lbs != null ? `${bag.completed_lbs} lbs` : "—"}
                </TableCell>
                <TableCell>{bag.completion_signal || "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {expandedBag ? (
        <Box sx={{ mt: 1 }}>
          <ShiftBagRecordRow
            key={expandedBag.bag_id}
            row={expandedBag}
            variant="at_vendor"
            referenceDateEt={referenceDateEt}
            defaultOpen
          />
        </Box>
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
