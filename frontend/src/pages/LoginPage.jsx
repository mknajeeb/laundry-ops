import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { authLogin, getPublicOrgBranding, setAuthSession } from "../api";

function sanitizeSlug(raw) {
  if (!raw) return "";
  try {
    return decodeURIComponent(String(raw))
      .toLowerCase()
      .replace(/[^a-z0-9-]/g, "")
      .slice(0, 64);
  } catch {
    return "";
  }
}

/**
 * Supports:
 * - /login — optional org slug field
 * - /login/:orgSlug — tenant bookmark (organization slug, e.g. /login/washpro if that tenant’s slug is washpro)
 */
function LoginPage({ onLoggedIn }) {
  const { orgSlug: orgSlugParam } = useParams();
  const slugFromRoute = useMemo(() => sanitizeSlug(orgSlugParam), [orgSlugParam]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [organizationSlug, setOrganizationSlug] = useState(
    () => localStorage.getItem("washpro_org_slug") || ""
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [branding, setBranding] = useState(null);

  useEffect(() => {
    if (slugFromRoute) {
      setOrganizationSlug(slugFromRoute);
      localStorage.setItem("washpro_org_slug", slugFromRoute);
    }
  }, [slugFromRoute]);

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
                {branding?.display_name || "Sign in"}
              </Typography>
            )}
          </Box>
          <Typography sx={{ color: "#64748b" }}>
            {branding?.display_name ? `Sign in to ${branding.display_name}` : "Sign in to continue"}
          </Typography>
          {slugFromRoute ? (
            <Typography variant="caption" color="text.secondary">
              Organization: <strong>{slugFromRoute}</strong>
              {" · "}
              <Link to="/login" style={{ color: "inherit" }}>
                Use a different organization
              </Link>
            </Typography>
          ) : null}
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
          {slugFromRoute ? (
            <TextField
              label="Organization"
              value={slugFromRoute}
              size="small"
              disabled
              helperText="This URL is for a single organization. Bookmark it for your team."
            />
          ) : (
            <TextField
              label="Organization slug (optional)"
              placeholder="e.g. washpro, veewash"
              value={organizationSlug}
              onChange={(e) => setOrganizationSlug(e.target.value)}
              autoComplete="organization"
              size="small"
              helperText="Required if the same username exists in more than one company. Or open your company login link: /login/your-slug"
            />
          )}
          <Button variant="contained" disabled={loading || !username || !password} onClick={submit}>
            {loading ? "Signing in..." : "Sign In"}
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}

export default LoginPage;
