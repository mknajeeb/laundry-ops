/* eslint-disable react-refresh/only-export-components -- context + hook pattern */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { getMe, login as apiLogin } from "../api";
import { clearOneSignalUser, syncOneSignalUser } from "../onesignalUser";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(
    () => localStorage.getItem("ta_token") || localStorage.getItem("washpro_token") || ""
  );
  const [user, setUser] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const [loading, setLoading] = useState(
    !!(localStorage.getItem("ta_token") || localStorage.getItem("washpro_token"))
  );

  const refreshMe = useCallback(async () => {
    const t = localStorage.getItem("ta_token") || localStorage.getItem("washpro_token");
    if (!t) {
      setUser(null);
      setPermissions([]);
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const res = await getMe();
      setUser(res.data.user);
      setPermissions(res.data.permissions || []);
    } catch {
      localStorage.removeItem("ta_token");
      setToken(localStorage.getItem("washpro_token") || "");
      setUser(null);
      setPermissions([]);
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
      setLoading(false);
      return;
    }
    refreshMe();
  }, [token, refreshMe]);

  useEffect(() => {
    if (!user?.id) {
      clearOneSignalUser();
      return;
    }
    syncOneSignalUser(user);
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
      loading,
      login,
      logout,
      refreshMe,
      hasPerm,
    }),
    [token, user, permissions, loading, login, logout, refreshMe, hasPerm]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
