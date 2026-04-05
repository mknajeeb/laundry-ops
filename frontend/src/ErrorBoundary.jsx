import { Component } from "react";
import { Box, Button, Typography } from "@mui/material";

/**
 * Catches render errors so production does not stay a blank white screen with no hint.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("App render error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <Box sx={{ p: 3, maxWidth: 560, mx: "auto", mt: 4 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Something went wrong loading the app
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Open the browser developer console (F12 → Console) for details. Try a hard refresh. If this
            is production, confirm the API URL (GitHub Actions variable{" "}
            <code style={{ fontSize: 12 }}>VITE_API_BASE</code>) matches your Flask host.
          </Typography>
          <Typography
            component="pre"
            sx={{
              fontSize: 12,
              p: 1.5,
              bgcolor: "action.hover",
              borderRadius: 1,
              overflow: "auto",
              whiteSpace: "pre-wrap",
            }}
          >
            {String(this.state.error?.message || this.state.error)}
          </Typography>
          <Button sx={{ mt: 2 }} variant="contained" onClick={() => window.location.reload()}>
            Reload
          </Button>
        </Box>
      );
    }
    return this.props.children;
  }
}
