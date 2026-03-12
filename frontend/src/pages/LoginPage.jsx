import { useState } from "react";
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { authLogin, setAuthSession } from "../api";

function LoginPage({ onLoggedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    try {
      setLoading(true);
      setError("");
      const res = await authLogin(username.trim(), password);
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
          <Typography sx={{ fontSize: 30, lineHeight: 1, color: "#0f172a" }}>Washpro</Typography>
          <Typography sx={{ color: "#64748b" }}>Sign in to continue</Typography>
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
          <Button variant="contained" disabled={loading || !username || !password} onClick={submit}>
            {loading ? "Signing in..." : "Sign In"}
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}

export default LoginPage;

