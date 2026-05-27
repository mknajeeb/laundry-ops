import { useState } from "react";
import {
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import FoldingUserSelect from "./FoldingUserSelect";
import FoldingEmployeeProductivityPanel from "./FoldingEmployeeProductivityPanel";
import ProcessingEmployeeProductivityPanel from "./ProcessingEmployeeProductivityPanel";

export default function EmployeeProductivitySection({
  selectedEmployee,
  onSelectEmployee,
  appliedDateStart,
  appliedDateEnd,
  appliedListDateField,
  searchTick,
  admin,
  onOpenTimeline,
  onOpenOrder,
  onMapUser,
}) {
  const [role, setRole] = useState("folding");
  const [viewMode, setViewMode] = useState("all");

  const showUserPanel = viewMode === "user" ? selectedEmployee : true;

  return (
    <>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={2}
        alignItems={{ sm: "center" }}
        flexWrap="wrap"
        sx={{ mb: 2 }}
      >
        <Typography variant="subtitle2" fontWeight={700}>
          Employee productivity
        </Typography>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={role}
          onChange={(_, v) => { if (v) setRole(v); }}
        >
          <ToggleButton value="folding">Folding</ToggleButton>
          <ToggleButton value="processing">Processing</ToggleButton>
        </ToggleButtonGroup>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={viewMode}
          onChange={(_, v) => { if (v) setViewMode(v); }}
        >
          <ToggleButton value="all">All users</ToggleButton>
          <ToggleButton value="user">Specific user</ToggleButton>
        </ToggleButtonGroup>
        {viewMode === "user" ? (
          <FoldingUserSelect
            label="User"
            value={selectedEmployee || ""}
            onChange={(v) => onSelectEmployee?.(v)}
          />
        ) : null}
      </Stack>

      {role === "folding" ? (
        viewMode === "all" ? (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Select a user under Employee analysis above, or switch to Specific user for folding productivity detail.
          </Typography>
        ) : null
      ) : null}

      {role === "folding" && viewMode === "user" && showUserPanel ? (
        <FoldingEmployeeProductivityPanel
          userName={selectedEmployee}
          appliedDateStart={appliedDateStart}
          appliedDateEnd={appliedDateEnd}
          appliedListDateField={appliedListDateField}
          searchTick={searchTick}
          admin={admin}
          onOpenTimeline={onOpenTimeline}
          onOpenOrder={onOpenOrder}
          onMapUser={onMapUser}
        />
      ) : null}

      {role === "processing" ? (
        <ProcessingEmployeeProductivityPanel
          viewMode={viewMode}
          userName={selectedEmployee}
          appliedDateStart={appliedDateStart}
          appliedDateEnd={appliedDateEnd}
          appliedListDateField={appliedListDateField}
          searchTick={searchTick}
          onOpenTimeline={onOpenTimeline}
          onOpenOrder={onOpenOrder}
          onMapUser={onMapUser}
          onSelectUser={(name) => {
            setViewMode("user");
            onSelectEmployee?.(name);
          }}
        />
      ) : null}
    </>
  );
}
