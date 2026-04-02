import { useEffect, useState } from "react";
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { authLogin, getPublicOrgBranding, setAuthSession } from "../api";

function LoginPage({ onLoggedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [organizationSlug, setOrganizationSlug] = useState(
    () => localStorage.getItem("washpro_org_slug") || ""
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);

  useEffect(() => {
    const slug = organizationSlug.trim().toLowerCase();
    if (!slug) {
      setBranding(null);
      return;
    }
    let cancelled = false;
    getPublicOrgBranding(slug)
      .then((res) => {
        if (!cancelled) setBranding(res.data);
      })
      .catch(() => {
        if (!cancelled) setBranding(null);
      });
    return () => {
      cancelled = true;
    };
  }, [organizationSlug]);

  const submit = async () => {
    try {
      setLoading(true);
      setError("");
      const slug = organizationSlug.trim();
      if (slug) localStorage.setItem("washpro_org_slug", slug.toLowerCase());
      const res = await authLogin(username.trim(), password, slug || null);
      const payload = res?.data || {};
      if (!payload?.token || !payload?.user) {
        throw new Error("Invalid login response.");
      }
      setAuthSession(payload);
      onLoggedIn?.(payload.user);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "linear-gradient(150deg, #f8fbff 0%, #eef4ff 45%, #f6fffe 100%)",
        p: 2,
      }}
    >
      <Paper sx={{ width: "100%", maxWidth: 420, p: 3, borderRadius: 3 }}>
        <Stack spacing={1.5}>
          <Box sx={{ minHeight: 40, display: "flex", alignItems: "center" }}>
            {branding?.logo_url ? (
              <Box
                component="img"
                src={branding.logo_url}
                alt=""
                sx={{ maxHeight: 40, maxWidth: "100%", objectFit: "contain" }}
              />
            ) : (
              <Typography sx={{ fontSize: 28, lineHeight: 1.1, color: "#0f172a", fontWeight: 700 }}>
                {branding?.display_name || "Washpro"}
              </Typography>
            )}
          </Box>
          <Typography sx={{ color: "#64748b" }}>
            Sign in{branding?.display_name ? ` to ${branding.display_name}` : ""}
          </Typography>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            size="small"
          />
          <TextField
            label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            size="small"
          />
          <TextField
            label="Organization slug (optional)"
            placeholder="e.g. washpro, veewash"
            value={organizationSlug}
            onChange={(e) => setOrganizationSlug(e.target.value)}
            autoComplete="organization"
            size="small"
            helperText="Required if the same username exists in more than one company."
          />
          <Button variant="contained" disabled={loading || !username || !password} onClick={submit}>
            {loading ? "Signing in..." : "Sign In"}
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}

export default LoginPage;

