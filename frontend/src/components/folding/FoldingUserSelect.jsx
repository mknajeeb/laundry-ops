import { Autocomplete, TextField } from "@mui/material";
import { useEffect, useState } from "react";
import { listFoldingUsers } from "../../api";

export default function FoldingUserSelect({
  label = "Employee / user",
  value,
  onChange,
  size = "small",
  sx,
  allowEmpty = true,
}) {
  const [options, setOptions] = useState([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listFoldingUsers();
        if (cancelled) return;
        const opts = res.data?.user_options || [];
        const names = opts.length
          ? opts
          : (res.data?.users || []).map((u) => ({ user_name: u, label: u }));
        setOptions(names);
      } catch {
        if (!cancelled) setOptions([]);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const selected = options.find((o) => o.user_name === value) || (value ? { user_name: value, label: value } : null);

  return (
    <Autocomplete
      size={size}
      sx={{ minWidth: 200, ...sx }}
      options={options}
      value={selected}
      onChange={(_, opt) => onChange(opt?.user_name || "")}
      getOptionLabel={(o) => o.label || o.user_name || ""}
      isOptionEqualToValue={(a, b) => a?.user_name === b?.user_name}
      renderInput={(params) => (
        <TextField {...params} label={label} placeholder={allowEmpty ? "All users" : "Select user"} />
      )}
    />
  );
}
