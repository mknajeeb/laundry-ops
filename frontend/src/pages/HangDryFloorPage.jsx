import { Navigate } from "react-router-dom";

/** Legacy separate Hang Dry PIN route — Hang Dry lives inside Revenue / Cash. */
export default function HangDryFloorPage() {
  return <Navigate to="/revenue-cash" replace />;
}
