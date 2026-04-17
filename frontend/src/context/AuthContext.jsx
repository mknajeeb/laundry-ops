/* eslint-disable react-refresh/only-export-components -- context + hook pattern */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { getTaBootstrap, login as apiLogin } from "../api";
import { clearOneSignalUser, syncOneSignalUser } from "../onesignalUser";

const AuthContext = createContext(null);

const DEFAULT_OPS_UI = {
  scan_lookup_enabled: true,
  browse_list_enabled: true,
  dryer_qr_scan_enabled: true,
};

export function AuthProvider({ children }) {
  const [token, setToken] = useState(
    () => localStorage.getItem("ta_token") || localStorage.getItem("washpro_token") || ""
  );
  const [user, setUser] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const [opsUi, setOpsUi] = useState(() => ({ ...DEFAULT_OPS_UI }));
  const [loading, setLoading] = useState(
    !!(localStorage.getItem("ta_token") || localStorage.getItem("washpro_token"))
  );
  const userRef = useRef(null);
  userRef.current = user;

  const refreshMe = useCallback(async () => {
    const t = localStorage.getItem("ta_token") || localStorage.getItem("washpro_token");
    if (!t) {
      setUser(null);
      setPermissions([]);
      setOpsUi({ ...DEFAULT_OPS_UI });
      setLoading(false);
      return;
    }
    try {
      if (!userRef.current?.id) setLoading(true);
      const res = await getTaBootstrap();
      setUser(res.data.user);
      setPermissions(res.data.permissions || []);
      const ou = res.data.ops_ui || {};
      setOpsUi({
        ...DEFAULT_OPS_UI,
        ...ou,
        scan_lookup_enabled: ou.scan_lookup_enabled !== false,
        browse_list_enabled: ou.browse_list_enabled !== false,
        dryer_qr_scan_enabled: ou.dryer_qr_scan_enabled !== false,
      });
    } catch {
      localStorage.removeItem("ta_token");
      setToken(localStorage.getItem("washpro_token") || "");
      setUser(null);
      setPermissions([]);
      setOpsUi({ ...DEFAULT_OPS_UI });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const sync = () => {
      setToken(localStorage.getItem("ta_token") || localStorage.getItem("washpro_token") || "");
    };
    sync();
    window.addEventListener("washpro-session-changed", sync);
    return () => window.removeEventListener("washpro-session-changed", sync);
  }, []);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setPermissions([]);
      setOpsUi({ ...DEFAULT_OPS_UI });
      setLoading(false);
      return;
    }
    refreshMe();
  }, [token, refreshMe]);

  /** Only unlink OneSignal after a real logout / session loss — not on first paint when user is null (avoids SDK errors on /login). */
  const hadAuthenticatedUserRef = useRef(false);

  useEffect(() => {
    if (user?.id) {
      hadAuthenticatedUserRef.current = true;
      const t = window.setTimeout(() => {
        try {
          syncOneSignalUser(user);
        } catch (e) {
          console.warn("OneSignal sync skipped", e);
        }
      }, 0);
      return () => window.clearTimeout(t);
    }
    if (hadAuthenticatedUserRef.current) {
      hadAuthenticatedUserRef.current = false;
      clearOneSignalUser();
    }
  }, [user]);

  const login = useCallback(async (email, password) => {
    const res = await apiLogin(email, password);
    const t = res.data.token;
    localStorage.setItem("ta_token", t);
    setToken(t);
  }, []);

  const logout = useCallback(() => {
    clearOneSignalUser();
    localStorage.removeItem("ta_token");
    setToken("");
    setUser(null);
    setPermissions([]);
    setOpsUi({ ...DEFAULT_OPS_UI });
  }, []);

  const hasPerm = useCallback(
    (key) => permissions.includes(key),
    [permissions]
  );

  const value = useMemo(
    () => ({
      token,
      user,
      permissions,
      opsUi,
      loading,
      login,
      logout,
      refreshMe,
      hasPerm,
    }),
    [token, user, permissions, opsUi, loading, login, logout, refreshMe, hasPerm]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
