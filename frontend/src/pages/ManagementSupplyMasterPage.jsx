import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import ManagementHubNav from "../components/management/ManagementHubNav";
import {
  getManagementSupplyMappings,
  getManagementSupplyProducts,
  getManagementSupplyProductsMeta,
  putManagementSupplyMappings,
  putManagementSupplyProduct,
  postManagementSupplyProduct,
} from "../api";
import { VEEWASH_DASHBOARD } from "../theme/veewashDashboard";

const EMPTY_PRODUCT = {
  product_code: "",
  supply_type: "DETERGENT",
  brand: "",
  product_name: "",
  vendor: "",
  form: "LIQUID",
  package_qty: "",
  package_unit: "oz",
  purchase_price_per_package: "",
  average_dose: "",
  dose_unit: "oz",
  is_active: true,
  legacy_report_key: "",
  notes: "",
  effective_from: "",
};

function fmtNum(v, digits = 4) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

function ProductEditor({ product, meta, onSave, saving }) {
  const [form, setForm] = useState(() => ({
    ...EMPTY_PRODUCT,
    ...product,
    package_qty: product?.package_qty ?? "",
    purchase_price_per_package: product?.purchase_price_per_package ?? "",
    average_dose: product?.average_dose ?? "",
    effective_from: product?.effective_from || "",
    is_active: product?.is_active !== false,
  }));

  useEffect(() => {
    setForm({
      ...EMPTY_PRODUCT,
      ...product,
      package_qty: product?.package_qty ?? "",
      purchase_price_per_package: product?.purchase_price_per_package ?? "",
      average_dose: product?.average_dose ?? "",
      effective_from: product?.effective_from || "",
      is_active: product?.is_active !== false,
    });
  }, [product]);

  const calc = useMemo(() => {
    const pkg = Number(form.package_qty);
    const dose = Number(form.average_dose);
    const price = Number(form.purchase_price_per_package);
    if (!(pkg > 0) || !(dose > 0)) {
      return { doses_per_package: null, cost_per_dose: null };
    }
    const doses = pkg / dose;
    const cost = price >= 0 && !Number.isNaN(price) ? price / doses : null;
    return { doses_per_package: doses, cost_per_dose: cost };
  }, [form.package_qty, form.average_dose, form.purchase_price_per_package]);

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <Box
      sx={{
        border: "1px solid #e5e7eb",
        borderRadius: 2,
        p: 1.5,
        bgcolor: "#fff",
      }}
    >
      <Typography sx={{ fontWeight: 800, fontSize: 14, mb: 1 }}>
        {product?.id ? `Edit · ${product.product_name || product.brand}` : "New product"}
      </Typography>
      <Stack spacing={1.25}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField
            size="small"
            label="Product ID"
            value={form.product_code || ""}
            onChange={(e) => setField("product_code", e.target.value)}
            fullWidth
          />
          <TextField
            size="small"
            select
            label="Supply Type"
            value={form.supply_type || "DETERGENT"}
            onChange={(e) => setField("supply_type", e.target.value)}
            fullWidth
          >
            {(meta?.supply_types || []).map((t) => (
              <MenuItem key={t.id} value={t.id}>
                {t.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField
            size="small"
            label="Brand"
            value={form.brand || ""}
            onChange={(e) => setField("brand", e.target.value)}
            fullWidth
            required
          />
          <TextField
            size="small"
            label="Product Name"
            value={form.product_name || ""}
            onChange={(e) => setField("product_name", e.target.value)}
            fullWidth
            required
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField
            size="small"
            label="Vendor"
            value={form.vendor || ""}
            onChange={(e) => setField("vendor", e.target.value)}
            fullWidth
          />
          <TextField
            size="small"
            select
            label="Form"
            value={form.form || "LIQUID"}
            onChange={(e) => setField("form", e.target.value)}
            fullWidth
          >
            {(meta?.forms || ["LIQUID", "POWDER"]).map((f) => (
              <MenuItem key={f} value={f}>
                {f}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField
            size="small"
            label="Package Qty"
            type="number"
            value={form.package_qty}
            onChange={(e) => setField("package_qty", e.target.value)}
            fullWidth
            required
          />
          <TextField
            size="small"
            label="Package Unit"
            value={form.package_unit || "oz"}
            onChange={(e) => setField("package_unit", e.target.value)}
            fullWidth
          />
          <TextField
            size="small"
            label="Price / Package"
            type="number"
            value={form.purchase_price_per_package}
            onChange={(e) => setField("purchase_price_per_package", e.target.value)}
            fullWidth
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField
            size="small"
            label="Avg Dose / Load"
            type="number"
            value={form.average_dose}
            onChange={(e) => setField("average_dose", e.target.value)}
            fullWidth
            required
          />
          <TextField
            size="small"
            label="Dose Unit"
            value={form.dose_unit || "oz"}
            onChange={(e) => setField("dose_unit", e.target.value)}
            fullWidth
          />
          <TextField
            size="small"
            label="Price effective from (ET)"
            type="date"
            value={form.effective_from || ""}
            onChange={(e) => setField("effective_from", e.target.value)}
            InputLabelProps={{ shrink: true }}
            fullWidth
            helperText={product?.id ? "New price row when price changes" : "Initial price date"}
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems="center">
          <TextField
            size="small"
            label="Legacy report key"
            value={form.legacy_report_key || ""}
            onChange={(e) => setField("legacy_report_key", e.target.value)}
            fullWidth
            helperText="Tide / Downy / OxiClean / All Free & Clear for current reports"
          />
          <FormControlLabel
            control={
              <Switch
                checked={Boolean(form.is_active)}
                onChange={(e) => setField("is_active", e.target.checked)}
              />
            }
            label="Active"
            sx={{ flexShrink: 0 }}
          />
        </Stack>
        <TextField
          size="small"
          label="Notes"
          value={form.notes || ""}
          onChange={(e) => setField("notes", e.target.value)}
          fullWidth
          multiline
          minRows={2}
        />
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            gap: 1,
            bgcolor: VEEWASH_DASHBOARD.primaryBlueLight,
            borderRadius: 1.5,
            p: 1.25,
          }}
        >
          <Box>
            <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>
              Doses / package
            </Typography>
            <Typography sx={{ fontWeight: 800 }}>{fmtNum(calc.doses_per_package, 2)}</Typography>
          </Box>
          <Box>
            <Typography sx={{ fontSize: 11, fontWeight: 700, color: "#64748b" }}>
              Cost / dose
            </Typography>
            <Typography sx={{ fontWeight: 800 }}>
              {calc.cost_per_dose == null ? "—" : `$${fmtNum(calc.cost_per_dose, 4)}`}
            </Typography>
          </Box>
        </Box>
        <Button
          variant="contained"
          disabled={saving}
          onClick={() => onSave(form)}
          sx={{ textTransform: "none", fontWeight: 700, alignSelf: "flex-start" }}
        >
          {saving ? "Saving…" : product?.id ? "Save product" : "Create product"}
        </Button>
      </Stack>
    </Box>
  );
}

function MappingEditor({ rules, supplyTypes, onSave, saving }) {
  const [rows, setRows] = useState(rules || []);

  useEffect(() => {
    setRows((rules || []).map((r) => ({ ...r, supply_types: [...(r.supply_types || [])] })));
  }, [rules]);

  const toggleType = (idx, typeId) => {
    setRows((prev) =>
      prev.map((row, i) => {
        if (i !== idx) return row;
        const set = new Set(row.supply_types || []);
        if (set.has(typeId)) set.delete(typeId);
        else set.add(typeId);
        return { ...row, supply_types: Array.from(set) };
      }),
    );
  };

  return (
    <Stack spacing={1.25}>
      <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
        Preference categories map to Supply Types. Active products of those types resolve into
        report keys (Tide / Downy / …) for the current Supply Usage page.
      </Typography>
      {rows.map((row, idx) => (
        <Box
          key={`${row.instructions}-${idx}`}
          sx={{ border: "1px solid #e5e7eb", borderRadius: 2, p: 1.25, bgcolor: "#fff" }}
        >
          <Typography sx={{ fontWeight: 800, fontSize: 13 }}>
            {row.instructions || (row.default ? "None / default" : "Rule")}
            {row.default ? " · DEFAULT" : ""}
          </Typography>
          <Typography sx={{ fontSize: 11, color: "#94a3b8", mb: 0.75 }}>
            Current projection: {(row.supplies || []).join(" + ") || "—"}
          </Typography>
          <Stack direction="row" flexWrap="wrap" gap={0.75}>
            {(supplyTypes || []).map((t) => {
              const on = (row.supply_types || []).includes(t.id);
              return (
                <Button
                  key={t.id}
                  size="small"
                  variant={on ? "contained" : "outlined"}
                  onClick={() => toggleType(idx, t.id)}
                  sx={{ textTransform: "none", fontWeight: 700 }}
                >
                  {t.label}
                </Button>
              );
            })}
          </Stack>
        </Box>
      ))}
      <Button
        variant="contained"
        disabled={saving}
        onClick={() => onSave(rows)}
        sx={{ textTransform: "none", fontWeight: 700, alignSelf: "flex-start" }}
      >
        {saving ? "Saving…" : "Save mappings"}
      </Button>
    </Stack>
  );
}

/** Management → Supply Product Master (Phase A). Compact PRODUCTS + MAPPINGS editors. */
export default function ManagementSupplyMasterPage() {
  const [tab, setTab] = useState(0);
  const [meta, setMeta] = useState(null);
  const [products, setProducts] = useState([]);
  const [rules, setRules] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const selected = useMemo(
    () => products.find((p) => p.id === selectedId) || null,
    [products, selectedId],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [metaRes, prodRes, mapRes] = await Promise.all([
        getManagementSupplyProductsMeta(),
        getManagementSupplyProducts(),
        getManagementSupplyMappings(),
      ]);
      setMeta(metaRes.data || null);
      setProducts(prodRes.data?.products || []);
      setNote(prodRes.data?.placeholder_note || metaRes.data?.placeholder_note || "");
      setRules(mapRes.data?.mapping_rules || []);
      if (!selectedId && (prodRes.data?.products || []).length) {
        setSelectedId(prodRes.data.products[0].id);
      }
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Unable to load supply master");
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    load();
    // intentionally once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSaveProduct = async (form) => {
    setSaving(true);
    setError("");
    try {
      const payload = {
        product_code: form.product_code || null,
        supply_type: form.supply_type,
        brand: form.brand,
        product_name: form.product_name,
        vendor: form.vendor || null,
        form: form.form,
        package_qty: Number(form.package_qty),
        package_unit: form.package_unit || "oz",
        average_dose: Number(form.average_dose),
        dose_unit: form.dose_unit || "oz",
        is_active: Boolean(form.is_active),
        legacy_report_key: form.legacy_report_key || null,
        notes: form.notes || null,
      };
      const priceVal =
        form.purchase_price_per_package === "" || form.purchase_price_per_package == null
          ? null
          : Number(form.purchase_price_per_package);
      const priceChanged =
        selected?.id
        && priceVal != null
        && Number(selected.purchase_price_per_package) !== priceVal;
      if (!selected?.id && priceVal != null) {
        payload.purchase_price_per_package = priceVal;
        if (form.effective_from) payload.effective_from = form.effective_from;
      } else if (priceChanged && form.effective_from) {
        payload.purchase_price_per_package = priceVal;
        payload.effective_from = form.effective_from;
        payload.price_notes = "Updated from Management Supply Master";
      }
      let saved;
      if (selected?.id) {
        const res = await putManagementSupplyProduct(selected.id, payload);
        saved = res.data;
      } else {
        const res = await postManagementSupplyProduct(payload);
        saved = res.data;
        setSelectedId(saved.id);
      }
      await load();
      if (saved?.id) setSelectedId(saved.id);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveMappings = async (rows) => {
    setSaving(true);
    setError("");
    try {
      const payload = rows.map((r) => ({
        instructions: r.instructions,
        supply_types: r.supply_types || [],
        supplies: r.supplies || [],
        default: Boolean(r.default),
        requires: r.requires,
        excludes: r.excludes,
      }));
      const res = await putManagementSupplyMappings({ mapping_rules: payload });
      setRules(res.data?.mapping_rules || []);
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || "Mapping save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box
      className="page"
      sx={{
        maxWidth: 720,
        mx: "auto",
        width: "100%",
        px: { xs: 1.5, sm: 2 },
        pb: 3,
        bgcolor: VEEWASH_DASHBOARD.pageBackground,
        minHeight: "100%",
      }}
    >
      <ManagementHubNav activeId="rinse_wf" />

      <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mt: 1.25, mb: 1 }}>
        <Box>
          <Typography sx={{ fontSize: 22, fontWeight: 800, lineHeight: 1.1 }}>
            Supply Master
          </Typography>
          <Typography sx={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>
            Products · Preference mappings
          </Typography>
        </Box>
        <Button
          component={RouterLink}
          to="/management/rinse-wf"
          size="small"
          sx={{ textTransform: "none", fontWeight: 700 }}
        >
          ← Rinse WF
        </Button>
      </Stack>

      {note ? (
        <Alert severity="info" sx={{ mb: 1.25, py: 0.5 }}>
          {note}
        </Alert>
      ) : null}
      {error ? (
        <Alert severity="error" sx={{ mb: 1.25 }}>
          {error}
        </Alert>
      ) : null}

      <Tabs
        value={tab}
        onChange={(_e, v) => setTab(v)}
        sx={{ mb: 1.25, minHeight: 36, "& .MuiTab-root": { textTransform: "none", fontWeight: 700, minHeight: 36 } }}
      >
        <Tab label="Products" />
        <Tab label="Mappings" />
      </Tabs>

      {loading ? (
        <Box sx={{ py: 4, textAlign: "center" }}>
          <CircularProgress size={22} />
        </Box>
      ) : tab === 0 ? (
        <Stack spacing={1.5}>
          <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
            {products.map((p) => (
              <Button
                key={p.id}
                size="small"
                variant={selectedId === p.id ? "contained" : "outlined"}
                onClick={() => setSelectedId(p.id)}
                sx={{ textTransform: "none", fontWeight: 700 }}
              >
                {p.brand}
                {!p.is_active ? " (off)" : ""}
              </Button>
            ))}
            <Button
              size="small"
              variant={selectedId == null ? "contained" : "outlined"}
              onClick={() => setSelectedId(null)}
              sx={{ textTransform: "none", fontWeight: 700 }}
            >
              + New
            </Button>
          </Stack>
          <Divider />
          <ProductEditor
            product={selected}
            meta={meta}
            onSave={handleSaveProduct}
            saving={saving}
          />
          {selected ? (
            <Typography sx={{ fontSize: 12, color: "#64748b" }}>
              As of {selected.as_of_date_et}: {fmtNum(selected.doses_per_package, 2)} doses/pkg ·{" "}
              {selected.cost_per_dose == null ? "—" : `$${fmtNum(selected.cost_per_dose, 4)}`}/dose
              {selected.effective_from ? ` · price from ${selected.effective_from}` : ""}
            </Typography>
          ) : null}
        </Stack>
      ) : (
        <MappingEditor
          rules={rules}
          supplyTypes={meta?.supply_types || []}
          onSave={handleSaveMappings}
          saving={saving}
        />
      )}
    </Box>
  );
}
