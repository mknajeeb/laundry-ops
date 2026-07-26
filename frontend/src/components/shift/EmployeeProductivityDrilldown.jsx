import { useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Collapse,
  FormControl,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ShiftBagRecordRow from "./ShiftBagRecordRow";
import CopyableBagId from "../CopyableBagId";
import {
  bagHasMissingPre,
  displayCustomerName,
  filterSessionsByRole,
  fmtDurationMinutes,
  resolveBagWeightLbs,
} from "../../utils/employeeProductivityHelpers";
import { formatFriendlyEtWall } from "../../utils/rinseTimeFormat";

function eventTs(bag) {
  return String(
    bag.processed_time
    || bag.processed_timestamp
    || bag.completion_time
    || bag.completion_timestamp
    || "",
  );
}

function fmtLbs(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${Number(v).toFixed(1)} lb`;
}

function shortTime(value) {
  if (value == null || value === "") return "—";
  const friendly = formatFriendlyEtWall(value);
  if (!friendly || friendly === "—") return "—";
  // "Jul 24, 8:00 AM ET" → "8:00 AM"
  const m = String(friendly).match(/(\d{1,2}:\d{2}\s*[AP]M)/i);
  return m ? m[1].replace(/\s+/g, " ") : friendly.replace(/\s*ET$/i, "").trim();
}

function WeightCell({ bag }) {
  const credited =
    bag.credited_weight_lbs != null ? Number(bag.credited_weight_lbs) : resolveBagWeightLbs(bag);
  const tip = [
    `Credited Weight (PRE): ${fmtLbs(credited)}`,
    `Evidence PRE: ${fmtLbs(bag.evidence_pre_weight_lbs ?? bag.pre_weight_lbs)}`,
    `Evidence POST: ${fmtLbs(bag.evidence_post_weight_lbs)}`,
    `Revenue Weight (POST): ${fmtLbs(bag.output_weight_lbs ?? bag.authoritative_post_weight_lbs ?? bag.post_weight_lbs)}`,
  ].join("\n");
  if (credited != null) {
    return (
      <Tooltip title={<Box sx={{ whiteSpace: "pre-line" }}>{tip}</Box>} arrow placement="top">
        <Typography component="span" variant="body2" fontWeight={700}>
          {`${credited} lbs`}
        </Typography>
      </Tooltip>
    );
  }
  return (
    <Tooltip title={<Box sx={{ whiteSpace: "pre-line" }}>{tip}</Box>} arrow placement="top">
      <Typography component="span" variant="body2" color="warning.main" sx={{ fontWeight: 600 }}>
        Missing PRE
      </Typography>
    </Tooltip>
  );
}

function normalizeProcessedBag(bag) {
  const completedLbs = resolveBagWeightLbs(bag);
  return {
    ...bag,
    completion_time: bag.completion_time || bag.processed_time || bag.processed_timestamp,
    completion_time_et: bag.completion_time_et || bag.processed_time_et,
    completion_signal: bag.completion_signal || bag.processed_signal,
    completed_lbs: completedLbs,
    weight_lbs: completedLbs,
  };
}

function sessionDisplay(bag) {
  if (bag?.session_assignment === "needs_review" || bag?.needs_review) return "Needs Review";
  if (bag?.session_assignment === "unassigned" || !bag?.session_id) return "Unassigned";
  // Never expose internal session_id in the UI.
  const code = String(bag.session_code || "").trim();
  const label = String(bag.session_assignment_label || "").trim();
  if (code && code !== String(bag.session_id || "")) return code;
  if (label && label !== String(bag.session_id || "") && label !== "Unassigned" && label !== "Needs Review") {
    return label;
  }
  return "SESSION";
}

function idleHeaderPhrase(session) {
  const minutes = session?.idle_minutes;
  if (minutes == null || Number.isNaN(Number(minutes))) {
    if (session?.idle_label) return `${session.idle_label} Idle`;
    return null;
  }
  const total = Math.max(0, Math.round(Number(minutes)));
  if (total >= 60) {
    const hours = Math.floor(total / 60);
    const mins = total % 60;
    if (mins) return `${hours}h ${mins}m Idle`;
    return `${hours}h Idle`;
  }
  return `${total} min Idle`;
}

function BagActionBar({ bag, onReviewBag, onSendBagForReview, sendingReview }) {
  if (!onReviewBag && !onSendBagForReview) return null;
  const missingPre = bagHasMissingPre(bag);
  return (
    <Stack
      direction="row"
      spacing={0.75}
      flexWrap="wrap"
      useFlexGap
      sx={{ mt: 1 }}
      onClick={(e) => e.stopPropagation()}
    >
      {onReviewBag ? (
        <Button
          size="small"
          variant="contained"
          disabled={sendingReview}
          onClick={() => onReviewBag(bag)}
          data-testid="employee-bag-review"
        >
          Review
        </Button>
      ) : null}
      {onSendBagForReview ? (
        <Button
          size="small"
          variant="outlined"
          disabled={sendingReview}
          onClick={() => onSendBagForReview(bag)}
          data-testid="employee-bag-send-for-review"
        >
          {missingPre ? "Send Missing PRE for Review" : "Send for Review"}
        </Button>
      ) : null}
    </Stack>
  );
}

function SessionAssignSelect({ bag, sessions, onAssignSession, assigning }) {
  if (typeof onAssignSession !== "function") {
    return (
      <Typography variant="body2" sx={{ whiteSpace: "nowrap" }}>
        {sessionDisplay(bag)}
      </Typography>
    );
  }
  const value = bag.session_id || "";
  return (
    <FormControl size="small" fullWidth sx={{ minWidth: 110 }} onClick={(e) => e.stopPropagation()}>
      <Select
        value={value}
        displayEmpty
        disabled={assigning}
        onChange={(e) => onAssignSession(bag, e.target.value || null)}
        sx={{
          fontSize: "0.8rem",
          minHeight: 44,
          "& .MuiSelect-select": { minHeight: 44, display: "flex", alignItems: "center", py: 1 },
        }}
        renderValue={(selected) => {
          if (!selected) return "Unassigned";
          const match = (sessions || []).find((s) => s.session_id === selected);
          if (match?.session_code) return match.session_code;
          if (bag.session_code && bag.session_code !== selected) return bag.session_code;
          return "SESSION";
        }}
      >
        <MenuItem value="">
          <em>Unassigned</em>
        </MenuItem>
        {(sessions || []).map((s) => (
          <MenuItem key={s.session_id} value={s.session_id}>
            <Box>
              <Typography variant="body2" fontWeight={700}>
                {s.session_code || "SESSION"}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {s.time_range_label
                  || `${shortTime(s.start_time)}–${
                    s.end_display === "Open" || s.end_display === "Unresolved"
                      ? s.end_display
                      : shortTime(s.end_time)
                  }`}
              </Typography>
            </Box>
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

function BagMobileRow({
  bag,
  expanded,
  onToggle,
  referenceDateEt,
  onReviewBag,
  onSendBagForReview,
  sendingReview,
  sessions,
  onAssignSession,
  assigning,
}) {
  const normalized = normalizeProcessedBag(bag);
  return (
    <Box
      onClick={onToggle}
      sx={{
        py: 1,
        borderBottom: "1px solid",
        borderColor: "divider",
        cursor: "pointer",
      }}
    >
      <Stack spacing={0.35}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Box sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap">
              <CopyableBagId
                bagId={bag.bag_id}
                sx={{ fontSize: "0.95rem", wordBreak: "break-all", color: "primary.main" }}
              />
              {bagHasMissingPre(bag) ? (
                <Chip label="Missing PRE" size="small" color="warning" sx={{ fontWeight: 700, fontSize: "0.7rem" }} />
              ) : null}
            </Stack>
            <Typography variant="body2" sx={{ wordBreak: "break-word" }}>
              {displayCustomerName(bag)}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block">
              {shortTime(normalized.completion_time_et || normalized.completion_time)}
              {" · "}
              {sessionDisplay(bag)}
              {" · Elapsed "}
              {bag.elapsed_time_label || fmtDurationMinutes(bag.elapsed_time_minutes)}
            </Typography>
          </Box>
          <Box sx={{ whiteSpace: "nowrap" }}>
            <WeightCell bag={bag} />
          </Box>
        </Stack>
      </Stack>
      <Collapse in={expanded} unmountOnExit>
        <Box sx={{ mt: 1 }} onClick={(e) => e.stopPropagation()}>
          <Typography variant="caption" display="block">
            Bag Start: {shortTime(bag.bag_start)}
          </Typography>
          <Typography variant="caption" display="block" sx={{ mb: 0.75 }}>
            Bag End: {shortTime(bag.bag_end || normalized.completion_time)}
          </Typography>
          <Typography variant="caption" fontWeight={700} display="block" sx={{ mb: 0.35 }}>
            Assign Session
          </Typography>
          <SessionAssignSelect
            bag={bag}
            sessions={sessions}
            onAssignSession={onAssignSession}
            assigning={assigning}
          />
          <BagActionBar
            bag={bag}
            onReviewBag={onReviewBag}
            onSendBagForReview={onSendBagForReview}
            sendingReview={sendingReview}
          />
          <Box sx={{ mt: 1 }}>
            <ShiftBagRecordRow
              row={normalized}
              variant="at_vendor"
              referenceDateEt={referenceDateEt}
              defaultOpen
              friendlyTimeDisplay
            />
          </Box>
        </Box>
      </Collapse>
    </Box>
  );
}

function BagTable({
  bags,
  expandedBagId,
  setExpandedBagId,
  referenceDateEt,
  onReviewBag,
  onSendBagForReview,
  sendingReview,
  sessions,
  onAssignSession,
  assigning,
}) {
  const sortedBags = useMemo(
    () => [...(bags || [])].sort((a, b) => eventTs(a).localeCompare(eventTs(b))),
    [bags],
  );
  const expandedBag = sortedBags.find((b) => b.bag_id === expandedBagId);
  const showActions = Boolean(onReviewBag || onSendBagForReview);

  if (!sortedBags.length) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 0.5 }}>
        No bags in this session.
      </Typography>
    );
  }

  return (
    <Box>
      <TableContainer sx={{ overflowX: "auto" }}>
        <Table size="small" aria-label="Completed bags">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 700, py: 1 }}>Time</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1 }}>Bag ID</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1 }}>Customer</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1 }}>Session</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1 }}>Bag Start</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1 }}>Bag End</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1 }} align="right">Elapsed</TableCell>
              <TableCell sx={{ fontWeight: 700, py: 1 }} align="right">PRE Lbs</TableCell>
              {showActions ? <TableCell sx={{ fontWeight: 700, py: 1 }}>Actions</TableCell> : null}
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedBags.map((bag) => {
              const normalized = normalizeProcessedBag(bag);
              return (
                <TableRow
                  key={bag.bag_id}
                  selected={expandedBagId === bag.bag_id}
                  hover
                  onClick={() => setExpandedBagId((prev) => (prev === bag.bag_id ? null : bag.bag_id))}
                  sx={{ cursor: "pointer", "& td": { py: 1 } }}
                >
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    {shortTime(normalized.completion_time_et || normalized.completion_time)}
                  </TableCell>
                  <TableCell>
                    <CopyableBagId bagId={bag.bag_id} />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 140, wordBreak: "break-word" }}>
                    {displayCustomerName(bag)}
                  </TableCell>
                  <TableCell sx={{ minWidth: 120 }}>
                    <SessionAssignSelect
                      bag={bag}
                      sessions={sessions}
                      onAssignSession={onAssignSession}
                      assigning={assigning}
                    />
                  </TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{shortTime(bag.bag_start)}</TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    {shortTime(bag.bag_end || normalized.completion_time)}
                  </TableCell>
                  <TableCell align="right">
                    {bag.elapsed_time_label || fmtDurationMinutes(bag.elapsed_time_minutes)}
                  </TableCell>
                  <TableCell align="right">
                    <WeightCell bag={normalized} />
                  </TableCell>
                  {showActions ? (
                    <TableCell onClick={(e) => e.stopPropagation()} sx={{ whiteSpace: "nowrap" }}>
                      <Stack direction="row" spacing={0.5}>
                        {onReviewBag ? (
                          <Button
                            size="small"
                            variant="contained"
                            disabled={sendingReview}
                            onClick={() => onReviewBag(bag)}
                          >
                            Review
                          </Button>
                        ) : null}
                        {onSendBagForReview ? (
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={sendingReview}
                            onClick={() => onSendBagForReview(bag)}
                          >
                            Send for Review
                          </Button>
                        ) : null}
                      </Stack>
                    </TableCell>
                  ) : null}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
      {expandedBag ? (
        <Box sx={{ mt: 1 }}>
          <BagActionBar
            bag={expandedBag}
            onReviewBag={onReviewBag}
            onSendBagForReview={onSendBagForReview}
            sendingReview={sendingReview}
          />
          <ShiftBagRecordRow
            key={expandedBag.bag_id}
            row={normalizeProcessedBag(expandedBag)}
            variant="at_vendor"
            referenceDateEt={referenceDateEt}
            defaultOpen
            friendlyTimeDisplay
          />
        </Box>
      ) : null}
    </Box>
  );
}

function groupBagsBySession(bags, sessions) {
  const sessionMap = Object.fromEntries((sessions || []).map((s) => [s.session_id, s]));
  const byId = {};
  const orphans = [];
  for (const bag of [...(bags || [])].sort((a, b) => eventTs(a).localeCompare(eventTs(b)))) {
    const sid = bag.session_id;
    if (
      sid
      && bag.session_assignment !== "unassigned"
      && bag.session_assignment !== "needs_review"
      && sessionMap[sid]
    ) {
      if (!byId[sid]) byId[sid] = { session: sessionMap[sid], bags: [] };
      byId[sid].bags.push(bag);
    } else {
      orphans.push(bag);
    }
  }
  const ordered = (sessions || [])
    .map((s) => byId[s.session_id] || { session: s, bags: [] })
    .filter((g) => g.bags.length > 0 || g.session);
  // Prefer sessions that have bags first, then empty sessions still listed
  const withBags = ordered.filter((g) => g.bags.length);
  const empty = ordered.filter((g) => !g.bags.length);
  const result = [...withBags, ...empty];
  if (orphans.length) result.push({ session: null, bags: orphans });
  return result;
}

function SessionGroup({
  group,
  expandedBagId,
  setExpandedBagId,
  referenceDateEt,
  onReviewBag,
  onSendBagForReview,
  sendingReview,
  sessions,
  onAssignSession,
  assigning,
  isMobile,
}) {
  const [open, setOpen] = useState(true);
  const session = group.session;
  const bagCount = session?.completed_bags ?? group.bags.length;
  const lbs = session?.credited_lbs;
  const rawCode = String(session?.session_code || "").trim();
  const code = session
    ? (rawCode && rawCode !== String(session.session_id || "") ? rawCode : "SESSION")
    : "Unassigned";
  const startLabel = session
    ? shortTime(session.start_time)
    : null;
  const endLabel = session
    ? (session.end_display === "Open" || session.end_display === "Unresolved"
      ? session.end_display
      : shortTime(session.end_time))
    : null;
  const idlePhrase = session ? idleHeaderPhrase(session) : null;
  const bagWord = bagCount === 1 ? "Bag" : "Bags";

  return (
    <Box sx={{ mb: 1.5 }}>
      <Stack
        direction="row"
        spacing={0.5}
        alignItems="flex-start"
        onClick={() => setOpen((v) => !v)}
        sx={{ cursor: "pointer", userSelect: "none", mb: 0.75 }}
      >
        <ExpandMoreIcon
          fontSize="small"
          sx={{
            mt: 0.15,
            transform: open ? "rotate(0deg)" : "rotate(-90deg)",
            transition: "transform 0.15s",
            color: "text.secondary",
            flexShrink: 0,
          }}
        />
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap>
            <Typography variant="subtitle2" fontWeight={800} sx={{ wordBreak: "break-word" }}>
              {session ? code : "Unassigned / Needs Review"}
            </Typography>
            {session?.timing_conflict ? (
              <Chip
                size="small"
                color="warning"
                label="Timing conflict"
                sx={{ fontWeight: 700, fontSize: "0.7rem", height: 22 }}
              />
            ) : null}
          </Stack>
          {session ? (
            <>
              <Typography variant="body2" color="text.secondary" sx={{ wordBreak: "break-word" }}>
                {startLabel} → {endLabel}
              </Typography>
              <Typography variant="body2" fontWeight={600} sx={{ wordBreak: "break-word" }}>
                {bagCount} {bagWord}
                {lbs != null ? ` · ${Number(lbs).toFixed(1)} PRE Lbs` : ""}
                {idlePhrase ? ` · ${idlePhrase}` : ""}
              </Typography>
            </>
          ) : (
            <Typography variant="body2" color="text.secondary">
              {group.bags.length} bag{group.bags.length === 1 ? "" : "s"}
            </Typography>
          )}
        </Box>
      </Stack>
      <Collapse in={open}>
        <Box sx={{ pl: { xs: 0.5, sm: 3 } }}>
          {isMobile ? (
            <Box>
              {group.bags.map((bag) => (
                <BagMobileRow
                  key={bag.bag_id}
                  bag={bag}
                  expanded={expandedBagId === bag.bag_id}
                  onToggle={() => setExpandedBagId((prev) => (prev === bag.bag_id ? null : bag.bag_id))}
                  referenceDateEt={referenceDateEt}
                  onReviewBag={onReviewBag}
                  onSendBagForReview={onSendBagForReview}
                  sendingReview={sendingReview}
                  sessions={sessions}
                  onAssignSession={onAssignSession}
                  assigning={assigning}
                />
              ))}
              {!group.bags.length ? (
                <Typography variant="body2" color="text.secondary">
                  No bags in this session.
                </Typography>
              ) : null}
            </Box>
          ) : (
            <BagTable
              bags={group.bags}
              expandedBagId={expandedBagId}
              setExpandedBagId={setExpandedBagId}
              referenceDateEt={referenceDateEt}
              onReviewBag={onReviewBag}
              onSendBagForReview={onSendBagForReview}
              sendingReview={sendingReview}
              sessions={sessions}
              onAssignSession={onAssignSession}
              assigning={assigning}
            />
          )}
        </Box>
      </Collapse>
    </Box>
  );
}

/** Drilldown: session-grouped completed bags (no separate sessions table). */
export default function EmployeeProductivityDrilldown({
  bags,
  sessions = [],
  roleFilterKeys = null,
  referenceDateEt,
  bagsLoading = false,
  onReviewBag,
  onSendBagForReview,
  sendingReview = false,
  onAssignSession,
  assigning = false,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [expandedBagId, setExpandedBagId] = useState(null);
  const visibleSessions = useMemo(
    () => filterSessionsByRole(sessions, roleFilterKeys),
    [sessions, roleFilterKeys],
  );
  const groups = useMemo(() => {
    const all = groupBagsBySession(bags || [], sessions || []);
    if (!roleFilterKeys?.length) return all.filter((g) => g.bags.length || !g.session);
    const kept = [];
    const moved = [];
    for (const g of all) {
      if (!g.session || roleFilterKeys.includes(g.session.role_filter_key)) {
        if (g.bags.length || !g.session) kept.push(g);
        else if (roleFilterKeys.includes(g.session.role_filter_key)) kept.push(g);
      } else if (g.bags.length) {
        moved.push(...g.bags);
      }
    }
    if (moved.length) {
      const orphan = kept.find((g) => !g.session);
      if (orphan) orphan.bags.push(...moved);
      else kept.push({ session: null, bags: moved });
    }
    return kept.filter((g) => g.bags.length > 0 || (g.session && roleFilterKeys.includes(g.session.role_filter_key)));
  }, [bags, sessions, roleFilterKeys]);

  if (bagsLoading || bags == null) {
    return (
      <Typography variant="body2" color="text.secondary">
        Loading bag details…
      </Typography>
    );
  }

  return (
    <Box sx={{ py: 0.5 }}>
      <Typography variant="subtitle2" fontWeight={800} sx={{ mb: 1 }}>
        Completed Bags ({(bags || []).length})
      </Typography>
      {!bags.length ? (
        <Typography variant="body2" color="text.secondary">
          No completed bags for this employee.
        </Typography>
      ) : (
        groups.map((group, idx) => (
          <SessionGroup
            key={group.session?.session_id || `orphan-${idx}`}
            group={group}
            expandedBagId={expandedBagId}
            setExpandedBagId={setExpandedBagId}
            referenceDateEt={referenceDateEt}
            onReviewBag={onReviewBag}
            onSendBagForReview={onSendBagForReview}
            sendingReview={sendingReview}
            sessions={visibleSessions}
            onAssignSession={onAssignSession}
            assigning={assigning}
            isMobile={isMobile}
          />
        ))
      )}
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
