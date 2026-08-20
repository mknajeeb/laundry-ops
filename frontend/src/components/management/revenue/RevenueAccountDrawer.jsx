import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Drawer,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import PlanningDatePicker from "../../datetime/PlanningDatePicker";
import { VEEWASH_DASHBOARD } from "../../../theme/veewashDashboard";
import { fmtMoney, moneyToInput, parseMoneyInput } from "./revenueFormat";

const drawerPaperSx = {
  width: { xs: "100%", sm: 420 },
  p: 0,
  bgcolor: VEEWASH_DASHBOARD.pageBackground,
};

function AccountListRow({ name, value, onClick, sub }) {
  return (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        display: "flex",
        width: "100%",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 1,
        textAlign: "left",
        m: 0,
        px: 1.5,
        py: 1.35,
        border: "none",
        borderBottom: "1px solid #e5e7eb",
        bgcolor: "#fff",
        cursor: "pointer",
        appearance: "none",
        fontFamily: "inherit",
        WebkitTapHighlightColor: "transparent",
        "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueLight },
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 700, fontSize: 15, color: "#0f172a" }}>{name}</Typography>
        {sub ? <Typography sx={{ fontSize: 12, color: "#94a3b8", mt: 0.15 }}>{sub}</Typography> : null}
      </Box>
      <Stack direction="row" alignItems="center" spacing={0.5}>
        <Typography sx={{ fontWeight: 800, fontSize: 15, color: VEEWASH_DASHBOARD.primaryBlueDark }}>
          {fmtMoney(value)}
        </Typography>
        <ChevronRightIcon sx={{ color: "#94a3b8", fontSize: 20 }} />
      </Stack>
    </Box>
  );
}

function BlankMoneyField({ label, value, onChange, disabled }) {
  return (
    <TextField
      label={label}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      disabled={disabled}
      size="small"
      fullWidth
      inputMode="decimal"
      placeholder=""
      sx={{ "& .MuiInputBase-root": { fontWeight: 700, bgcolor: "#fff" } }}
    />
  );
}

export default function RevenueAccountDrawer({
  open,
  groupId,
  data,
  dateEt,
  saving,
  onClose,
  onSaveNonRinse,
  onSaveWf,
  onSaveDhsAccount,
  focusAccountId = null,
  focusWf = false,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [step, setStep] = useState("list"); // list | non_rinse | dhs_account | rinse_detail
  const [selected, setSelected] = useState(null);

  const [ssCash, setSsCash] = useState("");
  const [ssCard, setSsCard] = useState("");
  const [doCash, setDoCash] = useState("");
  const [doCard, setDoCard] = useState("");

  const [volume, setVolume] = useState("");
  const [overrideOn, setOverrideOn] = useState(false);
  const [overrideAmt, setOverrideAmt] = useState("");
  const [pickupDate, setPickupDate] = useState("");
  const [processingDate, setProcessingDate] = useState("");
  const [deliveryDate, setDeliveryDate] = useState("");
  const [wfVolume, setWfVolume] = useState("");
  const [wfOverrideOn, setWfOverrideOn] = useState(false);
  const [wfOverrideAmt, setWfOverrideAmt] = useState("");

  useEffect(() => {
    if (!open) {
      setStep("list");
      setSelected(null);
      return;
    }
    setStep("list");
    setSelected(null);
  }, [open, groupId]);

  useEffect(() => {
    if (!open || groupId !== "dhs" || !focusAccountId) return;
    const row = (data?.dhs?.accounts || []).find((a) => a.account_id === focusAccountId);
    if (row) openDhs(row);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, groupId, focusAccountId, data?.dhs?.accounts]);

  useEffect(() => {
    if (!open || groupId !== "rinse" || !focusWf) return;
    setStep("wf_entry");
  }, [open, groupId, focusWf]);

  useEffect(() => {
    const nr = data?.non_rinse_revenue || data?.non_rinse || {};
    setSsCash(moneyToInput(nr.self_service?.cash));
    setSsCard(moneyToInput(nr.self_service?.card));
    setDoCash(moneyToInput(nr.drop_off?.cash));
    setDoCard(moneyToInput(nr.drop_off?.card));
    const wf = data?.rinse?.wf || {};
    setWfVolume(moneyToInput(wf.volume_lbs));
    setWfOverrideOn(false);
    setWfOverrideAmt(moneyToInput(wf.revenue));
  }, [data, open]);

  const title = useMemo(() => {
    if (step === "dhs_account" && selected) return selected.name;
    if (step === "non_rinse") return "Non-Rinse Entry";
    if (step === "wf_entry") return "Rinse WF";
    if (groupId === "rinse") return "Rinse";
    if (groupId === "non_rinse") return "Non-Rinse";
    if (groupId === "dhs") return "DHS Accounts";
    return "Accounts";
  }, [groupId, selected, step]);

  const openDhs = async (row) => {
    setSelected(row);
    setVolume(moneyToInput(row.volume));
    setOverrideOn(Boolean(row.use_revenue_override));
    setOverrideAmt(moneyToInput(row.use_revenue_override ? row.revenue : null));
    let pickup = row.pickup_date || "";
    let delivery = row.delivery_date || "";
    let scheduledPickup = "";
    let scheduledDelivery = "";
    try {
      const { getManagementRevenueSchedulePreview } = await import("../../../api");
      const res = await getManagementRevenueSchedulePreview(row.account_id, {
        processing_date: dateEt,
      });
      const defaults = res.data?.defaults || {};
      scheduledPickup = defaults.scheduled_pickup_date || "";
      scheduledDelivery = defaults.scheduled_delivery_date || "";
      if (!pickup && row.use_pickup_date) pickup = defaults.pickup_date || "";
      if (!delivery && row.use_delivery_date) delivery = defaults.delivery_date || "";
    } catch {
      /* ignore preview failures */
    }
    setPickupDate(pickup);
    setProcessingDate(row.processing_date || dateEt);
    setDeliveryDate(delivery);
    setSelected((prev) => ({
      ...row,
      ...prev,
      _scheduled_pickup_date: scheduledPickup,
      _scheduled_delivery_date: scheduledDelivery,
    }));
    setStep("dhs_account");
  };

  const calculatedPreview = useMemo(() => {
    if (!selected || selected.revenue_mode === "absolute" || overrideOn) return null;
    const rate = selected.pricing?.rate_per_unit;
    const vol = parseMoneyInput(volume);
    if (rate == null || vol == null) return null;
    return Number(vol) * Number(rate);
  }, [overrideOn, selected, volume]);

  const saveNonRinse = () => {
    onSaveNonRinse?.({
      self_service_cash: parseMoneyInput(ssCash),
      self_service_card: parseMoneyInput(ssCard),
      drop_off_cash: parseMoneyInput(doCash),
      drop_off_card: parseMoneyInput(doCard),
    });
  };

  const saveDhs = () => {
    if (!selected) return;
    const body = {
      account_id: selected.account_id,
      name: selected.name,
      dr_commercial_account_id: selected.dr_commercial_account_id,
      revenue_mode: selected.revenue_mode,
      use_revenue_override: overrideOn,
      volume: selected.revenue_mode === "absolute" || overrideOn ? undefined : parseMoneyInput(volume),
      revenue:
        selected.revenue_mode === "absolute" || overrideOn
          ? parseMoneyInput(overrideAmt)
          : calculatedPreview,
      pickup_date: selected.use_pickup_date ? pickupDate || null : null,
      // Visible prefill: when Processing Date is enabled, send the shown value (defaults to entry date).
      processing_date:
        selected.use_processing_date !== false ? processingDate || dateEt || null : null,
      delivery_date: selected.use_delivery_date ? deliveryDate || null : null,
      scheduled_pickup_date: selected._scheduled_pickup_date || null,
      scheduled_delivery_date: selected._scheduled_delivery_date || null,
      date_override: Boolean(
        (selected._scheduled_pickup_date && pickupDate && pickupDate !== selected._scheduled_pickup_date) ||
          (selected._scheduled_delivery_date &&
            deliveryDate &&
            deliveryDate !== selected._scheduled_delivery_date),
      ),
    };
    if (selected.revenue_mode !== "absolute" && !overrideOn) {
      body.volume = parseMoneyInput(volume);
      if (body.volume != null && calculatedPreview != null) body.revenue = calculatedPreview;
    }
    onSaveDhsAccount?.(body);
  };

  const rinse = data?.rinse || {};
  const dhsAccounts = data?.dhs?.accounts || [];

  return (
    <Drawer
      anchor={isMobile ? "bottom" : "right"}
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: {
          ...drawerPaperSx,
          ...(isMobile
            ? { width: "100%", maxHeight: "92vh", borderTopLeftRadius: 16, borderTopRightRadius: 16 }
            : {}),
        },
      }}
    >
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        sx={{ px: 1.5, py: 1.25, borderBottom: "1px solid #e5e7eb", bgcolor: "#fff" }}
      >
        <Box>
          {step !== "list" ? (
            <Button size="small" onClick={() => setStep("list")} sx={{ textTransform: "none", mb: 0.25 }}>
              ← Back
            </Button>
          ) : null}
          <Typography sx={{ fontWeight: 800, fontSize: 16 }}>{title}</Typography>
        </Box>
        <Button size="small" onClick={onClose} sx={{ textTransform: "none" }}>
          Close
        </Button>
      </Stack>

      <Box sx={{ overflow: "auto", flex: 1 }}>
        {step === "list" && groupId === "rinse" ? (
          <Stack spacing={0}>
            <AccountListRow
              name="Rinse WF"
              value={rinse.wf?.revenue}
              sub={
                rinse.wf?.entered
                  ? `${rinse.wf?.volume_lbs ?? "—"} lb · Processing ${dateEt}`
                  : rinse.wf?.placeholder
                    ? "Pricing not configured — set in Accounts"
                    : "Missing — tap to enter"
              }
              onClick={() => setStep("wf_entry")}
            />
            <AccountListRow
              name="Rinse HD"
              value={rinse.hd?.revenue}
              sub={`${rinse.hd?.orders ?? 0} complete orders · from HD production`}
              onClick={() => setStep("rinse_detail")}
            />
          </Stack>
        ) : null}

        {step === "list" && groupId === "non_rinse" ? (
          <Stack spacing={0}>
            <AccountListRow
              name="Self Service"
              value={data?.non_rinse_revenue?.self_service?.total}
              onClick={() => setStep("non_rinse")}
            />
            <AccountListRow
              name="Drop Off"
              value={data?.non_rinse_revenue?.drop_off?.total}
              onClick={() => setStep("non_rinse")}
            />
          </Stack>
        ) : null}

        {step === "list" && groupId === "dhs" ? (
          <Stack spacing={0}>
            {!dhsAccounts.length ? (
              <Typography sx={{ p: 2, color: "#64748b", fontSize: 13 }}>No DHS accounts configured.</Typography>
            ) : (
              dhsAccounts.map((row) => (
                <AccountListRow
                  key={row.account_id}
                  name={row.name}
                  value={row.revenue}
                  sub={row.parent_name && row.parent_name !== "DHS" ? row.parent_name : undefined}
                  onClick={() => openDhs(row)}
                />
              ))
            )}
          </Stack>
        ) : null}

        {step === "wf_entry" ? (
          <Stack spacing={1.5} sx={{ p: 2 }}>
            <Typography sx={{ fontWeight: 800 }}>Rinse WF</Typography>
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>
              Processing Date {dateEt} · blank is Missing (not $0)
            </Typography>
            <BlankMoneyField label="Volume (lb)" value={wfVolume} onChange={setWfVolume} />
            {rinse.wf?.pricing?.rate_per_unit != null && !wfOverrideOn ? (
              <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: "#F0FAFB", border: "1px solid #e5e7eb" }}>
                <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>Calculated</Typography>
                <Typography sx={{ fontWeight: 900, fontSize: 18 }}>
                  {fmtMoney(
                    parseMoneyInput(wfVolume) != null
                      ? Number(wfVolume) * Number(rinse.wf.pricing.rate_per_unit)
                      : rinse.wf?.revenue,
                  )}
                </Typography>
              </Box>
            ) : null}
            <FormControlLabel
              control={
                <Switch
                  checked={wfOverrideOn}
                  onChange={(e) => setWfOverrideOn(e.target.checked)}
                />
              }
              label="Use revenue override"
            />
            {wfOverrideOn ? (
              <BlankMoneyField label="Revenue override" value={wfOverrideAmt} onChange={setWfOverrideAmt} />
            ) : null}
            <Button
              variant="contained"
              disabled={saving}
              onClick={() =>
                onSaveWf?.({
                  volume_lbs: parseMoneyInput(wfVolume),
                  revenue: wfOverrideOn ? parseMoneyInput(wfOverrideAmt) : undefined,
                  use_revenue_override: wfOverrideOn,
                })
              }
              sx={{ textTransform: "none", fontWeight: 800, minHeight: 48 }}
            >
              Save WF
            </Button>
          </Stack>
        ) : null}

        {step === "rinse_detail" ? (
          <Stack spacing={1.5} sx={{ p: 2 }}>
            <Box sx={{ p: 1.5, borderRadius: 1.5, bgcolor: "#fff", border: `1px solid ${VEEWASH_DASHBOARD.hdBorder}` }}>
              <Typography sx={{ fontWeight: 800 }}>Rinse HD</Typography>
              <Typography sx={{ fontSize: 22, fontWeight: 900, mt: 0.5, color: VEEWASH_DASHBOARD.hdTeal }}>
                {fmtMoney(rinse.hd?.revenue)}
              </Typography>
              <Typography sx={{ fontSize: 12, color: "#64748b", mt: 0.5 }}>
                {rinse.hd?.orders ?? 0} complete orders · from HD production (read-only)
              </Typography>
            </Box>
          </Stack>
        ) : null}

        {step === "non_rinse" ? (
          <Stack spacing={1.5} sx={{ p: 2 }}>
            <Typography sx={{ fontWeight: 800, fontSize: 13 }}>Self Service</Typography>
            <BlankMoneyField label="Cash" value={ssCash} onChange={setSsCash} />
            <BlankMoneyField label="Card" value={ssCard} onChange={setSsCard} />
            <Typography sx={{ fontWeight: 800, fontSize: 13, pt: 0.5 }}>Drop Off</Typography>
            <BlankMoneyField label="Cash" value={doCash} onChange={setDoCash} />
            <BlankMoneyField label="Card" value={doCard} onChange={setDoCard} />
            <Button
              variant="contained"
              onClick={saveNonRinse}
              disabled={saving}
              sx={{
                mt: 1,
                fontWeight: 800,
                textTransform: "none",
                bgcolor: VEEWASH_DASHBOARD.primaryBlue,
                "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
              }}
            >
              {saving ? "Saving…" : "Save Non-Rinse"}
            </Button>
          </Stack>
        ) : null}

        {step === "dhs_account" && selected ? (
          <Stack spacing={1.5} sx={{ p: 2 }}>
            {selected.use_pickup_date ? (
              <PlanningDatePicker value={pickupDate || dateEt} onChange={setPickupDate} label="Pickup Date" />
            ) : null}
            {selected.use_processing_date ? (
              <PlanningDatePicker
                value={processingDate || dateEt}
                onChange={setProcessingDate}
                label="Processing Date"
              />
            ) : null}
            {selected.use_delivery_date ? (
              <PlanningDatePicker value={deliveryDate || dateEt} onChange={setDeliveryDate} label="Delivery Date" />
            ) : null}

            {selected.revenue_mode === "absolute" ? (
              <BlankMoneyField label="Absolute Revenue" value={overrideAmt} onChange={setOverrideAmt} />
            ) : (
              <>
                {!overrideOn ? (
                  <>
                    <BlankMoneyField label="Volume (lb)" value={volume} onChange={setVolume} />
                    {selected.pricing?.rate_per_unit != null ? (
                      <Typography sx={{ fontSize: 13, color: "#64748b" }}>
                        Rate ${Number(selected.pricing.rate_per_unit).toFixed(2)}/lb
                      </Typography>
                    ) : null}
                    <Box sx={{ p: 1.25, borderRadius: 1.5, bgcolor: VEEWASH_DASHBOARD.primaryBlueLight }}>
                      <Typography sx={{ fontSize: 12, fontWeight: 700, color: "#64748b" }}>Calculated Revenue</Typography>
                      <Typography sx={{ fontWeight: 900, fontSize: 20, color: VEEWASH_DASHBOARD.primaryBlueDark }}>
                        {fmtMoney(calculatedPreview)}
                      </Typography>
                    </Box>
                  </>
                ) : null}
                {selected.allow_override ? (
                  <FormControlLabel
                    control={<Switch checked={overrideOn} onChange={(e) => setOverrideOn(e.target.checked)} />}
                    label="Use Revenue Override"
                    sx={{ "& .MuiFormControlLabel-label": { fontWeight: 700, fontSize: 13 } }}
                  />
                ) : null}
                {overrideOn ? (
                  <BlankMoneyField label="Absolute Revenue" value={overrideAmt} onChange={setOverrideAmt} />
                ) : null}
              </>
            )}

            <Button
              variant="contained"
              onClick={saveDhs}
              disabled={saving}
              sx={{
                mt: 1,
                fontWeight: 800,
                textTransform: "none",
                bgcolor: VEEWASH_DASHBOARD.primaryBlue,
                "&:hover": { bgcolor: VEEWASH_DASHBOARD.primaryBlueDark },
              }}
            >
              {saving ? "Saving…" : "Save Account"}
            </Button>
          </Stack>
        ) : null}
      </Box>
    </Drawer>
  );
}
