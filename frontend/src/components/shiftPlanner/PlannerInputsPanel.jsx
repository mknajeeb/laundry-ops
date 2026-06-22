import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Chip,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { HELPER_RULES, OPERATIONAL_STRATEGIES } from "../../shiftPlanner/constants";
import { splitFromCounts } from "../../shiftPlanner/plannerHelpers";

function numField(key, label, inputs, onChange, { min = 0, step = 1, helperText } = {}) {
  return (
    <TextField
      label={label}
      type="number"
      size="small"
      value={inputs[key]}
      onChange={(e) => onChange(key, e.target.value)}
      inputProps={{ min, step }}
      helperText={helperText}
      fullWidth
    />
  );
}

export default function PlannerInputsPanel({ inputs, onChange, onStrategyChange }) {
  const bagCount = Number(inputs.bag_count) || 0;
  const orders2Wash = Number(inputs.orders_using_2_washers) || 0;
  const orders2Dry = Number(inputs.orders_using_2_dryers) || 0;
  const orders1Wash = Math.max(0, bagCount - orders2Wash);
  const orders1Dry = Math.max(0, bagCount - orders2Dry);
  const totals = splitFromCounts(bagCount, orders2Wash, orders2Dry);
  const showCustom = inputs.operational_strategy === "custom";

  return (
    <Stack spacing={1}>
      <Accordion defaultExpanded disableGutters elevation={0} sx={{ border: "1px solid #e2e8f0", "&:before": { display: "none" } }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 44 }}>
          <Typography variant="subtitle2" fontWeight={700}>Shift setup</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0 }}>
          <Stack spacing={1.25}>
            <TextField label="Shift start" size="small" value={inputs.start_time} onChange={(e) => onChange("start_time", e.target.value)} fullWidth />
            <TextField label="Target / end time" size="small" value={inputs.target_time} onChange={(e) => onChange("target_time", e.target.value)} fullWidth />
            {numField("bag_count", "Total bags / orders", inputs, onChange, { min: 1 })}
            {numField("avg_lbs_per_bag", "Average lb per bag", inputs, onChange, { min: 1 })}
            <Grid container spacing={1}>
              <Grid item xs={6}>{numField("washer_count", "Washers", inputs, onChange, { min: 1 })}</Grid>
              <Grid item xs={6}>{numField("dryer_count", "Dryers", inputs, onChange, { min: 1 })}</Grid>
              <Grid item xs={6}>{numField("wash_cycle_min", "Wash cycle (min)", inputs, onChange, { min: 1 })}</Grid>
              <Grid item xs={6}>{numField("dry_cycle_min", "Dry cycle (min)", inputs, onChange, { min: 1 })}</Grid>
              <Grid item xs={12}>{numField("batch_size", "Batch size", inputs, onChange, { min: 6, step: 2 })}</Grid>
            </Grid>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded disableGutters elevation={0} sx={{ border: "1px solid #e2e8f0", "&:before": { display: "none" } }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 44 }}>
          <Typography variant="subtitle2" fontWeight={700}>Load split</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0 }}>
          <Stack spacing={1.25}>
            {numField("orders_using_1_washers", "Orders using 1 washer", inputs, (k, v) => {
              onChange(k, v);
              onChange("orders_using_2_washers", Math.max(0, bagCount - Number(v || 0)));
            }, { min: 0 })}
            {numField("orders_using_2_washers", "Orders using 2 washers", inputs, (k, v) => {
              onChange(k, v);
              onChange("orders_using_1_washers", Math.max(0, bagCount - Number(v || 0)));
            }, { min: 0 })}
            {numField("orders_using_1_dryers", "Orders using 1 dryer", inputs, (k, v) => {
              onChange(k, v);
              onChange("orders_using_2_dryers", Math.max(0, bagCount - Number(v || 0)));
            }, { min: 0 })}
            {numField("orders_using_2_dryers", "Orders using 2 dryers", inputs, (k, v) => {
              onChange(k, v);
              onChange("orders_using_1_dryers", Math.max(0, bagCount - Number(v || 0)));
            }, { min: 0 })}
            <Alert severity="info" sx={{ py: 0.5 }}>
              <Typography variant="caption" display="block">
                {orders1Wash} × 1 washer + {orders2Wash} × 2 washers = <strong>{totals.wash.washerLoads}</strong> washer loads
              </Typography>
              <Typography variant="caption" display="block">
                {orders1Dry} × 1 dryer + {orders2Dry} × 2 dryers = <strong>{totals.dry.dryerLoads}</strong> dryer loads
              </Typography>
            </Alert>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded disableGutters elevation={0} sx={{ border: "1px solid #e2e8f0", "&:before": { display: "none" } }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 44 }}>
          <Typography variant="subtitle2" fontWeight={700}>Labor & roles</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0 }}>
          <Stack spacing={1.25}>
            <Grid container spacing={1}>
              <Grid item xs={6}>{numField("weigh_min_per_bag", "Weigh min / bag", inputs, onChange, { min: 0, step: 0.5 })}</Grid>
              <Grid item xs={6}>{numField("sort_min_per_bag", "Sort min / bag", inputs, onChange, { min: 0, step: 0.5 })}</Grid>
              <Grid item xs={6}>{numField("fold_min_per_bag", "Fold min / bag", inputs, onChange, { min: 0, step: 0.5 })}</Grid>
              <Grid item xs={6}>{numField("folder_count", "Folders", inputs, onChange, { min: 1 })}</Grid>
              <Grid item xs={6}>{numField("sorter_count", "Sorters (auto if blank)", inputs, onChange, { min: 1 })}</Grid>
              <Grid item xs={6}>{numField("weigher_count", "Weighers (auto if blank)", inputs, onChange, { min: 0 })}</Grid>
              <Grid item xs={6}>{numField("washer_person_count", "Washer persons", inputs, onChange, { min: 1 })}</Grid>
            </Grid>
            <FormControl size="small" fullWidth>
              <InputLabel>Helper rule</InputLabel>
              <Select label="Helper rule" value={inputs.helper_rule} onChange={(e) => onChange("helper_rule", e.target.value)}>
                {HELPER_RULES.map((r) => (
                  <MenuItem key={r.value} value={r.value}>{r.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <Typography variant="caption" fontWeight={700} color="text.secondary">Washer person timing</Typography>
            <Grid container spacing={1}>
              <Grid item xs={6}>{numField("load_washer_min", "Load washer", inputs, onChange, { min: 0 })}</Grid>
              <Grid item xs={6}>{numField("unload_washer_min", "Unload washer", inputs, onChange, { min: 0 })}</Grid>
              <Grid item xs={6}>{numField("load_dryer_min", "Load dryer", inputs, onChange, { min: 0 })}</Grid>
              <Grid item xs={6}>{numField("unload_dryer_min", "Unload dryer", inputs, onChange, { min: 0 })}</Grid>
              <Grid item xs={12}>{numField("washer_transfer_min", "Transfer buffer (min)", inputs, onChange, { min: 0 })}</Grid>
            </Grid>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Accordion defaultExpanded disableGutters elevation={0} sx={{ border: "1px solid #e2e8f0", "&:before": { display: "none" } }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 44 }}>
          <Typography variant="subtitle2" fontWeight={700}>Strategy</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ pt: 0 }}>
          <Stack spacing={1.25}>
            <FormControl size="small" fullWidth>
              <InputLabel>Operational strategy</InputLabel>
              <Select
                label="Operational strategy"
                value={inputs.operational_strategy}
                onChange={(e) => onStrategyChange(e.target.value)}
              >
                {OPERATIONAL_STRATEGIES.map((s) => (
                  <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>
                ))}
              </Select>
            </FormControl>
            {showCustom ? (
              <Box>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.75 }}>
                  Custom mode — adjust weighing and washing below.
                </Typography>
                <Grid container spacing={1}>
                  <Grid item xs={12}>
                    <FormControl size="small" fullWidth>
                      <InputLabel>Washing strategy</InputLabel>
                      <Select label="Washing strategy" value={inputs.washing_strategy} onChange={(e) => onChange("washing_strategy", e.target.value)}>
                        <MenuItem value="batch_washing">Batch washing</MenuItem>
                        <MenuItem value="sort_while_drying">Sort while drying</MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12}>
                    <FormControl size="small" fullWidth>
                      <InputLabel>Weighing mode</InputLabel>
                      <Select label="Weighing mode" value={inputs.weighing_mode} onChange={(e) => onChange("weighing_mode", e.target.value)}>
                        <MenuItem value="separate_lane">Separate weigh lane</MenuItem>
                        <MenuItem value="during_sort">Weigh while sorting</MenuItem>
                        <MenuItem value="upfront">Weigh all at shift start</MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                </Grid>
              </Box>
            ) : (
              <Chip size="small" label={OPERATIONAL_STRATEGIES.find((s) => s.value === inputs.operational_strategy)?.label} />
            )}
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
