import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMatch, useNavigate, useParams } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Checkbox,
  Divider,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  OutlinedInput,
  Paper,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { ArrowBack, Add, DeleteOutline, ExpandMore } from "@mui/icons-material";
import {
  createTaUser,
  deleteTaUser,
  getAuthUser,
  getEmploymentCategories,
  getGeofences,
  getOrgHrLookups,
  getPlatformOrganizations,
  getPlatformUserProfile,
  getRoles,
  getTaRoles,
  getTaUser,
  putPlatformUserProfile,
  putUserEmploymentCategories,
  putUserGeofences,
  updateTaUser,
  updateUser,
  getTaUserHrProfile,
  getTaTaxFormYearSettings,
  putTaUserHrProfile,
} from "../api";
import I9DetailsForm, { emptyI9, emptyPreparer } from "../components/hr/I9DetailsForm";
import { useStreetAutocomplete } from "../components/GooglePlacesAutocomplete";
import {
  normalizeTaxIdDigits,
  isValidEmail,
  normalizeUsPhoneDigits,
  isValidUsPhone10,
  localDateYmd,
} from "../utils/validation";
import {
  coalesceWorkJsonFromHr,
  emergencyContactsJsonLooksLikeWorkJsonSpill,
} from "../utils/mailingMerge";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import {
  hasPlatformAdminRole,
  hasTenantPortalAccess,
  normalizedRoles,
} from "../utils/platformAccess";

function emptyEmergencyRow() {
  return { name: "", relationship: "", phone: "", alt_phone: "" };
}

/** True for 1099/temp-style categories: payroll may collect TIN here. W-2 workers use Compliance / I-9. */
function employmentCategoryUsesPayrollTaxId(cats, catId) {
  const id = String(catId || "").trim();
  if (!id) return true;
  const c = cats.find((x) => String(x.id) === id);
  if (!c) return true;
  const name = String(c.name || "").toLowerCase();
  const code = String(c.code || "").toUpperCase();
  if (code.includes("1099") || name.includes("1099") || name.includes("contractor")) return true;
  if (code.includes("TEMP") || /\btemp\b|\btemporary\b/.test(name)) return true;
  return false;
}

function ProfileSection({ n, title, hint, children }) {
  return (
    <Box sx={{ mb: 0 }}>
      <Typography component="h2" variant="subtitle1" sx={{ fontWeight: 600, mb: hint ? 0.25 : 0.5 }}>
        {n ? `${n}. ` : ""}
        {title}
      </Typography>
      {hint ? (
        <Typography variant="body2" color="text.secondary" display="block" sx={{ mb: 1.25 }}>
          {hint}
        </Typography>
      ) : (
        <Box sx={{ height: 6 }} />
      )}
      {children}
    </Box>
  );
}

function emptyW4Compliance() {
  return {
    filing_status: "",
    is_nonresident_alien: false,
    nra_allow_step3_4: false,
    exempt: false,
    step2_multiple_jobs: "",
    two_jobs_only: false,
    step3a_amount: "",
    step3b_amount: "",
    step3_other_credits_amount: "",
    dependents_amount: "",
    w4_helper_children_under_17: "",
    w4_helper_other_dependents: "",
    w4_helper_total_dependents: "",
    other_income: "",
    deductions: "",
    extra_withholding: "",
  };
}

function normalizeLoadedW4Compliance(raw) {
  const c = { ...emptyW4Compliance(), ...raw };
  const fs = c.filing_status;
  const legacy = {
    single: "single_or_mfs",
    married_separate: "single_or_mfs",
    married_joint: "mfj_or_qss",
    head: "hoh",
    nonresident: "single_or_mfs",
  };
  if (fs && legacy[fs]) {
    c.filing_status = legacy[fs];
    if (fs === "nonresident") c.is_nonresident_alien = true;
  }
  if (c.is_nonresident_alien) {
    c.exempt = false;
    c.filing_status = "single_or_mfs";
  }
  return c;
}

/** Live preview for W-4 Step 3 auto amounts (matches backend w4_step3_compute defaults). */
function w4Step3PreviewAmounts(w4Compliance, w4TaxSettings) {
  const rateC = Number(w4TaxSettings?.w4_step3_child_credit_amount ?? 2000) || 2000;
  const rateO = Number(w4TaxSettings?.w4_step3_other_dependent_credit_amount ?? 500) || 500;
  const allowOther =
    w4TaxSettings == null ||
    (w4TaxSettings.w4_allow_other_credits !== 0 && w4TaxSettings.w4_allow_other_credits !== false);

  const intish = (v) => {
    if (v == null || v === "") return 0;
    const n = parseInt(String(v).trim(), 10);
    return Number.isFinite(n) ? Math.max(0, n) : 0;
  };

  const childN = intish(
    w4Compliance?.w4_qualifying_children_under_17_count ?? w4Compliance?.w4_helper_children_under_17,
  );
  const otherN = intish(
    w4Compliance?.w4_other_dependents_count ?? w4Compliance?.w4_helper_other_dependents,
  );

  let otherCred = 0;
  if (allowOther && w4Compliance?.w4_step3_other_credits_amount != null && w4Compliance?.w4_step3_other_credits_amount !== "") {
    const s = String(w4Compliance.w4_step3_other_credits_amount).replace(/,/g, "");
    const x = parseFloat(s);
    otherCred = Number.isFinite(x) ? x : 0;
  }

  const a = childN * rateC;
  const b = otherN * rateO;
  const t = a + b + otherCred;

  const fmt = (n) => {
    if (!Number.isFinite(n)) return "0";
    const r = Math.round(n * 100) / 100;
    if (Number.isInteger(r)) return String(r);
    return String(r);
  };

  return {
    a: fmt(a),
    b: fmt(b),
    t: fmt(t),
    rateC: fmt(rateC),
    rateO: fmt(rateO),
  };
}

function emptyNyIt2104Compliance() {
  return {
    Resident: "",
    "Resident of Yonkers": "",
    "line 1": "",
    "line 2": "",
    "line 3": "",
    "line 4": "",
    "line 5": "",
  };
}

/** NY IT-2104 "Status" PDF field — derived from federal W-4 filing_status in the UI. */
function nyIt2104StatusFromW4Filing(fs) {
  const m = {
    single_or_mfs: "Single",
    mfj_or_qss: "Married",
    hoh: "Head of household",
    single: "Single",
    married_joint: "Married",
    married_separate: "Married, but withhold at higher single rate",
    head: "Head of household",
    nonresident: "Nonresident alien",
  };
  return m[fs] || "";
}

function normalizeNyYesNo(v) {
  const s = String(v || "").toLowerCase();
  if (s === "yes" || s === "y") return "Yes";
  if (s === "no" || s === "n") return "No";
  if (v === "Yes" || v === "No") return v;
  return "";
}

function formatPayrollAddressLine(line1, apt, city, state, zip) {
  const tail = [city, state, zip].filter((x) => String(x || "").trim()).join(" ");
  const a = String(line1 || "").trim();
  const ap = String(apt || "").trim();
  const block = [a, ap].filter(Boolean).join(", ");
  if (!block && !tail) return null;
  if (!tail) return block || null;
  if (!block) return tail;
  return `${block}, ${tail}`;
}

/** Split payroll_profiles.address free-text (line1 + "City, ST ZIP") into fields for the form. */
function parseTaAddressBlob(blob) {
  const t = String(blob || "").trim();
  if (!t) return { line1: "", city: "", state: "", zip: "" };
  const lines = t.split(/\n/).map((s) => s.trim()).filter(Boolean);
  let line1 = lines[0] || "";
  let city = "";
  let state = "";
  let zip = "";
  if (lines.length >= 2) {
    const last = lines[lines.length - 1];
    const m = last.match(/^([^,]+),\s*([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)$/);
    if (m) {
      city = m[1].trim();
      state = m[2].toUpperCase();
      zip = m[3];
      line1 = lines.length === 2 ? lines[0] : lines.slice(0, -1).join(", ");
    }
  }
  return { line1, city, state, zip };
}

const WORKSPACE_TAB_FLOW = ["summary", "basic", "payroll", "compliance", "emergency", "notes", "documents"];

const ONBOARD_STEP_INDEX = {
  basic: 0,
  payroll: 1,
  compliance: 2,
  emergency: 3,
  notes: 4,
  documents: 5,
};

function coerceEmergencyContactsJson(raw) {
  if (raw == null) return [];
  if (emergencyContactsJsonLooksLikeWorkJsonSpill(raw)) return [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw === "string") {
    try {
      const p = JSON.parse(raw);
      if (emergencyContactsJsonLooksLikeWorkJsonSpill(p)) return [];
      return Array.isArray(p) ? p : [];
    } catch {
      return [];
    }
  }
  return [];
}

/** Legacy bug: emergency JSON was stored in hr.notes; move into contacts and clear notes. */
function trySplitEmergencyFromNotes(notesRaw) {
  if (notesRaw == null || notesRaw === "") return { notesText: "", migratedEmergency: null };
  const s = typeof notesRaw === "string" ? notesRaw.trim() : String(notesRaw).trim();
  if (!s.startsWith("[")) {
    return { notesText: typeof notesRaw === "string" ? notesRaw : s, migratedEmergency: null };
  }
  try {
    const parsed = JSON.parse(s);
    if (!Array.isArray(parsed) || !parsed.length) {
      return { notesText: typeof notesRaw === "string" ? notesRaw : s, migratedEmergency: null };
    }
    const row0 = parsed[0];
    if (row0 && typeof row0 === "object" && ("phone" in row0 || "name" in row0 || "relationship" in row0)) {
      return { notesText: "", migratedEmergency: parsed };
    }
  } catch {
    /* ignore */
  }
  return { notesText: typeof notesRaw === "string" ? notesRaw : s, migratedEmergency: null };
}

function validateComplianceForSave({
  firstName,
  lastName,
  addrState,
  complianceI9,
  payrollTaxIdDigits,
  w4Compliance,
  nyIt2104Fields,
  t,
}) {
  const fn = String(firstName || "").trim();
  const ln = String(lastName || "").trim();
  if (!fn || !ln) return t("profile.errComplianceNames");
  const ssn = normalizeTaxIdDigits(complianceI9.ssn);
  const payrollSsn = normalizeTaxIdDigits(payrollTaxIdDigits || "");
  // Payroll tab collects SSN; I-9 section uses omitIdentityFields, so TIN may only exist on payroll.
  if (ssn.length !== 9 && payrollSsn.length !== 9) return t("profile.errComplianceSsn");
  if (!String(complianceI9.citizenship || "").trim()) return t("profile.errComplianceCitizenship");
  if (complianceI9.citizenship === "3" && !String(complianceI9.uscis_a_number || "").trim()) {
    return t("profile.errComplianceUscis");
  }
  if (complianceI9.citizenship === "4") {
    if (!String(complianceI9.work_authorization_expiration || "").trim()) {
      return t("profile.errComplianceWorkAuth");
    }
    if (!String(complianceI9.form_i94_admission || "").trim()) return t("profile.errComplianceI94");
    if (!String(complianceI9.foreign_passport || "").trim()) return t("profile.errCompliancePassport");
  }
  const route = complianceI9.document_route || "list_a";
  if (route === "list_a" && !String(complianceI9.list_a_title || "").trim()) {
    return t("profile.errComplianceListA");
  }
  if (route === "list_bc") {
    if (!String(complianceI9.list_b_title || "").trim()) return t("profile.errComplianceListB");
    if (!String(complianceI9.list_c_title || "").trim()) return t("profile.errComplianceListC");
  }
  if (!String(complianceI9.employer_authorized_representative || "").trim()) {
    return t("profile.errComplianceEmployerRep");
  }
  const preps = complianceI9.preparers || [];
  if (!preps.length) return t("profile.errCompliancePreparerMin");
  for (let i = 0; i < preps.length; i++) {
    const p = { ...emptyPreparer(), ...preps[i] };
    if (!String(p.last_name || "").trim() || !String(p.first_name || "").trim()) {
      return t("profile.errCompliancePreparerName");
    }
    if (
      !String(p.address || "").trim() ||
      !String(p.city || "").trim() ||
      !String(p.state || "").trim() ||
      !String(p.zip || "").trim()
    ) {
      return t("profile.errCompliancePreparerAddr");
    }
  }
  if (!String(w4Compliance.filing_status || "").trim()) {
    return t("profile.errComplianceW4Status");
  }
  if (w4Compliance.exempt && w4Compliance.is_nonresident_alien) {
    return t("profile.errComplianceW4NraExempt");
  }
  const st = String(addrState || "").trim().toUpperCase();
  if (st === "NY") {
    const nyc = normalizeNyYesNo(nyIt2104Fields.Resident);
    const yon = normalizeNyYesNo(nyIt2104Fields["Resident of Yonkers"]);
    if (!nyc || !yon) return t("profile.errComplianceNyResidency");
    if (nyc === "Yes" && yon === "Yes") return t("profile.errComplianceNyMutual");
  }
  return null;
}

export default function UserProfilePage({ user: sessionUser }) {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { hasPerm, user: authBootstrapUser } = useAuth();
  const platformMode = Boolean(useMatch("/platform/users/:userId"));

  const uid = Number(userId);
  const mergedRoleSet = useMemo(() => {
    return new Set([...normalizedRoles(sessionUser), ...normalizedRoles(authBootstrapUser)]);
  }, [sessionUser, authBootstrapUser]);
  const canWashproUserAdmin =
    mergedRoleSet.has("ADMIN") ||
    mergedRoleSet.has("SUPER_ADMIN") ||
    mergedRoleSet.has("PLATFORM_ADMIN");
  const canTaView = hasPerm("users.view");
  const canTaEdit = hasPerm("users.edit");
  const canTaAdd = hasPerm("users.add");
  /** Must match /employees ADMIN gate + backend implicit perms — do not rely on permissions[] alone. */
  const canEditPayrollRecords = platformMode ? canTaEdit : canTaEdit || canWashproUserAdmin;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [removingPayroll, setRemovingPayroll] = useState(false);
  const [error, setError] = useState("");
  const [hasPayroll, setHasPayroll] = useState(false);
  const [onboardingFreeNav, setOnboardingFreeNav] = useState(false);
  const [onboardMaxStep, setOnboardMaxStep] = useState(0);
  const canEditHrExtras = canEditPayrollRecords || (canTaAdd && !hasPayroll);

  const [orgOptions, setOrgOptions] = useState([]);
  const [organizationId, setOrganizationId] = useState("");

  const [wpUsername, setWpUsername] = useState("");
  const [wpDisplay, setWpDisplay] = useState("");
  const [wpActive, setWpActive] = useState(true);
  const [wpRoles, setWpRoles] = useState([]);
  const [wpPassword, setWpPassword] = useState("");

  const [washproRoleChoices, setWashproRoleChoices] = useState([]);
  const [taRoleChoices, setTaRoleChoices] = useState([]);
  const [geofences, setGeofences] = useState([]);
  const [cats, setCats] = useState([]);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const [mobile, setMobile] = useState("");
  const [addrLine1, setAddrLine1] = useState("");
  const [addrApt, setAddrApt] = useState("");
  const [addrCity, setAddrCity] = useState("");
  const [addrState, setAddrState] = useState("");
  const [addrZip, setAddrZip] = useState("");
  const [middleInitial, setMiddleInitial] = useState("");
  const [otherLastName, setOtherLastName] = useState("");
  const [profileDob, setProfileDob] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [languagePreference, setLanguagePreference] = useState("");
  const [supervisorName, setSupervisorName] = useState("");
  const [rehireStartDate, setRehireStartDate] = useState("");
  const [itinSsn, setItinSsn] = useState("");
  const [itinLast4Hint, setItinLast4Hint] = useState("");
  const [emergency, setEmergency] = useState(() => [emptyEmergencyRow()]);
  const [profileHrNotes, setProfileHrNotes] = useState("");
  const [hireDate, setHireDate] = useState("");
  const [termDate, setTermDate] = useState("");
  const [rehired, setRehired] = useState(false);
  const [payrollActive, setPayrollActive] = useState(true);
  const [roleId, setRoleId] = useState("");
  const [payrollPassword, setPayrollPassword] = useState("");
  const [rehireParentId, setRehireParentId] = useState("");
  const [priorEmployeeId, setPriorEmployeeId] = useState("");

  const [geofenceIds, setGeofenceIds] = useState([]);
  const [catRows, setCatRows] = useState([
    { employment_category_id: "", effective_from: new Date().toISOString().slice(0, 10), effective_to: "" },
  ]);

  const [workspaceTab, setWorkspaceTab] = useState("basic");
  const [complianceI9, setComplianceI9] = useState(() => emptyI9());
  const [w4Compliance, setW4Compliance] = useState(() => emptyW4Compliance());
  const [nyIt2104Fields, setNyIt2104Fields] = useState(() => emptyNyIt2104Compliance());
  const [deptCode, setDeptCode] = useState("");
  const [jobTitleCode, setJobTitleCode] = useState("");
  const [employmentStatusCode, setEmploymentStatusCode] = useState("");
  const [languageCode, setLanguageCode] = useState("");
  const [laundryExperience, setLaundryExperience] = useState("");
  const [lkDept, setLkDept] = useState([]);
  const [lkJob, setLkJob] = useState([]);
  const [lkStatus, setLkStatus] = useState([]);
  const [lkLang, setLkLang] = useState([]);
  const [w4TaxSettings, setW4TaxSettings] = useState(null);

  const catalogsPrimedRef = useRef(false);
  const profileLoadSeqRef = useRef(0);

  const mapsForPayrollTab = !platformMode && workspaceTab === "payroll";
  const mapsForComplianceTab = !platformMode && workspaceTab === "compliance";
  const { inputRef: payrollStreetRef, hasMapsKey: hasPayrollMaps } = useStreetAutocomplete((place) => {
    setAddrLine1(place.street || "");
    setAddrCity(place.city || "");
    setAddrState(place.state || "");
    setAddrZip(place.zip || "");
  }, mapsForPayrollTab);

  useEffect(() => {
    if (!platformMode && workspaceTab === "more") setWorkspaceTab("basic");
  }, [platformMode, workspaceTab]);

  useEffect(() => {
    if (platformMode || workspaceTab !== "compliance") return;
    const y = Number(w4Compliance.w4_tax_year) || new Date().getFullYear();
    let cancelled = false;
    getTaTaxFormYearSettings(y)
      .then((res) => {
        if (!cancelled) setW4TaxSettings(res.data?.settings ?? null);
      })
      .catch(() => {
        if (!cancelled) setW4TaxSettings(null);
      });
    return () => {
      cancelled = true;
    };
  }, [platformMode, workspaceTab, w4Compliance.w4_tax_year]);

  const w4Step3Preview = useMemo(
    () => w4Step3PreviewAmounts(w4Compliance, w4TaxSettings),
    [
      w4Compliance.w4_qualifying_children_under_17_count,
      w4Compliance.w4_other_dependents_count,
      w4Compliance.w4_helper_children_under_17,
      w4Compliance.w4_helper_other_dependents,
      w4Compliance.w4_step3_other_credits_amount,
      w4TaxSettings,
    ],
  );

  useEffect(() => {
    if (!uid || platformMode) return;
    const done = localStorage.getItem(`profile_onboard_done_${uid}`) === "1";
    setOnboardingFreeNav(done);
    if (done) return;
    const s = localStorage.getItem(`profile_onboard_step_${uid}`);
    const n = s != null && s !== "" ? Number(s) : 0;
    setOnboardMaxStep(Number.isFinite(n) ? Math.max(0, Math.min(5, n)) : 0);
  }, [uid, platformMode]);

  useEffect(() => {
    setItinSsn("");
  }, [uid]);

  useEffect(() => {
    if (platformMode) return;
    if (!jobTitleCode || !lkJob.length) return;
    const row = lkJob.find((x) => String(x.code) === String(jobTitleCode));
    const label = String(row?.label || "").trim();
    if (!label) return;
    setJobTitle((prev) => (String(prev || "").trim() ? prev : label));
  }, [platformMode, jobTitleCode, lkJob]);

  useEffect(() => {
    if (platformMode) return;
    if (!languageCode || !lkLang.length) return;
    const row = lkLang.find((x) => String(x.code) === String(languageCode));
    const label = String(row?.label || "").trim();
    if (!label) return;
    setLanguagePreference((prev) => (String(prev || "").trim() ? prev : label));
  }, [platformMode, languageCode, lkLang]);

  const canUse = useMemo(() => {
    if (platformMode) return true;
    // Route may require ADMIN, but roles/perms can disagree (e.g. API permission without literal ADMIN string).
    if (canWashproUserAdmin) return true;
    if (hasTenantPortalAccess(sessionUser) && (canTaView || canTaEdit || canTaAdd)) return true;
    return false;
  }, [platformMode, canWashproUserAdmin, sessionUser, canTaView, canTaEdit, canTaAdd]);

  const hasCategory = Boolean(String(catRows[0]?.employment_category_id || "").trim());
  const showPayrollTaxIdField = employmentCategoryUsesPayrollTaxId(cats, catRows[0]?.employment_category_id);
  const payrollCoreOk =
    firstName.trim() &&
    lastName.trim() &&
    email.trim() &&
    isValidEmail(email.trim()) &&
    isValidUsPhone10(normalizeUsPhoneDigits(mobile));
  const emergencySaveOk = (() => {
    const ec0 = emergency[0];
    const ecPhone = normalizeUsPhoneDigits(ec0?.phone);
    return String(ec0?.name || "").trim() && isValidUsPhone10(ecPhone);
  })();

  const isWorkspaceTabLocked = useCallback(
    (tab) => {
      if (!platformMode && !onboardingFreeNav) {
        if (tab === "summary") return false;
        const ord = ONBOARD_STEP_INDEX[tab];
        if (ord !== undefined && ord > onboardMaxStep) return true;
      }
      if (!hasPayroll) {
        if (tab === "summary" || tab === "basic" || tab === "payroll") return false;
        return true;
      }
      const req =
        tab === "payroll"
          ? ["category"]
          : tab === "compliance" || tab === "emergency"
            ? ["category", "payrollCore"]
            : tab === "notes" || tab === "documents"
              ? ["category", "payrollCore", "emergency"]
              : [];
      if (req.includes("category") && !hasCategory) return true;
      if (req.includes("payrollCore") && !payrollCoreOk) return true;
      if (req.includes("emergency") && !emergencySaveOk) return true;
      return false;
    },
    [platformMode, onboardingFreeNav, onboardMaxStep, hasPayroll, hasCategory, payrollCoreOk, emergencySaveOk],
  );

  const seedFromTa = useCallback((ta, auth) => {
    setHasPayroll(true);
    setFirstName(ta.first_name || "");
    setLastName(ta.last_name || "");
    setEmail(ta.email || "");
    setEmployeeId(ta.employee_id || "");
    setMobile(ta.mobile || "");
    const parsedAddr = parseTaAddressBlob(ta.address);
    setAddrLine1(parsedAddr.line1);
    setAddrCity(parsedAddr.city);
    setAddrState(parsedAddr.state);
    setAddrZip(parsedAddr.zip);
    setItinLast4Hint(ta.itin_ssn_last4 || "");
    setEmergency([emptyEmergencyRow()]);
    setProfileHrNotes("");
    setHireDate(ta.hire_date ? String(ta.hire_date).slice(0, 10) : "");
    setTermDate(ta.termination_date ? String(ta.termination_date).slice(0, 10) : "");
    setRehired(!!ta.rehired);
    setPayrollActive(!!ta.active);
    setRoleId(ta.role_id != null ? String(ta.role_id) : "");
    setRehireParentId(
      ta.rehire_parent_user_id != null && ta.rehire_parent_user_id !== ""
        ? String(ta.rehire_parent_user_id)
        : ta.rehire_parent_id != null && ta.rehire_parent_id !== ""
          ? String(ta.rehire_parent_id)
          : "",
    );
    setPriorEmployeeId(ta.prior_employee_id || "");
    setDeptCode(ta.dept_code != null && ta.dept_code !== "" ? String(ta.dept_code) : "");
    setJobTitleCode(ta.job_title_code != null && ta.job_title_code !== "" ? String(ta.job_title_code) : "");
    setEmploymentStatusCode(
      ta.employment_status_code != null && ta.employment_status_code !== ""
        ? String(ta.employment_status_code)
        : "",
    );
    setLanguageCode(ta.language_code != null && ta.language_code !== "" ? String(ta.language_code) : "");
    setLaundryExperience(
      ta.laundry_experience === null || ta.laundry_experience === undefined
        ? ""
        : ta.laundry_experience
          ? "1"
          : "0",
    );
    setGeofenceIds((ta.geofence_ids || []).map(Number));
    const assigns = ta.employment_assignments || [];
    setCatRows(
      assigns.length > 0
        ? assigns.map((a) => ({
            employment_category_id: a.employment_category_id,
            effective_from: String(a.effective_from).slice(0, 10),
            effective_to: a.effective_to ? String(a.effective_to).slice(0, 10) : "",
          }))
        : [
            {
              employment_category_id: "",
              effective_from: new Date().toISOString().slice(0, 10),
              effective_to: "",
            },
          ],
    );
  }, [uid]);

  const buildHrExtendedPutBody = useCallback(
    () => {
      const pay9 = normalizeTaxIdDigits(itinSsn);
      const i9Digits = normalizeTaxIdDigits(complianceI9?.ssn || "");
      const i9ForSave =
        pay9.length === 9 && i9Digits.length !== 9
          ? { ...complianceI9, ssn: pay9 }
          : complianceI9;
      const jobTitleLookup =
        jobTitleCode &&
        String(lkJob.find((x) => String(x.code) === String(jobTitleCode))?.label || "").trim();
      const languageLookup =
        languageCode &&
        String(lkLang.find((x) => String(x.code) === String(languageCode))?.label || "").trim();
      const jobTitleForWork = jobTitle.trim() || jobTitleLookup || "";
      const languageForWork = languagePreference.trim() || languageLookup || "";
      return {
      date_of_birth: profileDob.trim() || null,
      notes: profileHrNotes.trim() || null,
      emergency_contacts_json: emergency.filter(
        (r) => r.name || r.phone || r.relationship || r.alt_phone,
      ),
      work_json: {
        address_line1: addrLine1.trim() || null,
        mailing_address_line1: addrLine1.trim() || null,
        address_line2: addrApt.trim() || null,
        city: addrCity.trim() || null,
        state: addrState.trim() || null,
        zip: addrZip.trim() || null,
        middle_initial: middleInitial.trim().slice(0, 1) || null,
        other_last_name: otherLastName.trim() || null,
        job_title: jobTitleForWork || null,
        language_preference: languageForWork || null,
        supervisor_name: supervisorName.trim() || null,
        rehire_start_date: rehireStartDate.trim() || null,
        i9: i9ForSave,
        w4: { compliance: w4Compliance },
        ny_it2104: {
          ...Object.fromEntries(
            Object.entries(nyIt2104Fields).filter(([, v]) => String(v || "").trim() !== ""),
          ),
          ...(w4Compliance.filing_status
            ? { Status: nyIt2104StatusFromW4Filing(w4Compliance.filing_status) }
            : {}),
        },
      },
    };
    },
    [
      profileDob,
      profileHrNotes,
      emergency,
      addrLine1,
      addrApt,
      addrCity,
      addrState,
      addrZip,
      middleInitial,
      otherLastName,
      jobTitle,
      languagePreference,
      jobTitleCode,
      languageCode,
      lkJob,
      lkLang,
      supervisorName,
      rehireStartDate,
      itinSsn,
      complianceI9,
      w4Compliance,
      nyIt2104Fields,
    ],
  );

  const applyHrFromProfile = useCallback((hrData) => {
    if (!hrData || hrData.error) return;
    const rawHr = hrData.hr;
    const h =
      rawHr != null && typeof rawHr === "object" && !Array.isArray(rawHr) ? rawHr : {};
    const split = trySplitEmergencyFromNotes(h.notes);
    let notesText = split.notesText !== "" ? split.notesText : h.notes || "";
    if (split.migratedEmergency) notesText = "";
    setProfileHrNotes(notesText || "");
    const rawDob = h.date_of_birth;
    let ymd = rawDob ? String(rawDob).slice(0, 10) : "";
    const todayLocal = localDateYmd();
    if (ymd && ymd >= todayLocal) ymd = "";
    setProfileDob(ymd);
    let em = coerceEmergencyContactsJson(h.emergency_contacts_json);
    if (split.migratedEmergency?.length && (!em || !em.length)) em = split.migratedEmergency;
    const cleaned = em.filter((r) => r && (r.name || r.phone || r.relationship || r.alt_phone));
    setEmergency(cleaned.length ? cleaned.map((r) => ({ ...emptyEmergencyRow(), ...r })) : [emptyEmergencyRow()]);
    const w = coalesceWorkJsonFromHr(h);
    const l1 = w.address_line1 || w.mailing_address_line1;
    if (l1) setAddrLine1(l1);
    if (w.address_line2 != null && w.address_line2 !== "") setAddrApt(String(w.address_line2));
    if (w.city) setAddrCity(w.city);
    if (w.state) setAddrState(w.state);
    if (w.zip) setAddrZip(w.zip);
    setMiddleInitial((w.middle_initial || "").toString().slice(0, 1));
    setOtherLastName(w.other_last_name || w.other_last_names || "");
    setJobTitle(w.job_title || "");
    setLanguagePreference(w.language_preference || "");
    setSupervisorName(w.supervisor_name || "");
    setRehireStartDate(w.rehire_start_date ? String(w.rehire_start_date).slice(0, 10) : "");
    const i9raw = w.i9 && typeof w.i9 === "object" ? w.i9 : {};
    setComplianceI9({ ...emptyI9(), ...i9raw });
    const i9Stored = normalizeTaxIdDigits(i9raw.ssn || "");
    if (i9Stored.length === 9) {
      setItinSsn(i9Stored);
    } else {
      setItinSsn("");
    }
    const w4 = w.w4 && typeof w.w4 === "object" ? w.w4 : {};
    const w4c = w4.compliance && typeof w4.compliance === "object" ? w4.compliance : {};
    setW4Compliance(normalizeLoadedW4Compliance(w4c));
    const ny = w.ny_it2104 && typeof w.ny_it2104 === "object" ? w.ny_it2104 : {};
    const nyPick = {};
    for (const k of Object.keys(emptyNyIt2104Compliance())) {
      if (ny[k] != null && String(ny[k]).trim() !== "") {
        const raw = String(ny[k]).trim();
        nyPick[k] =
          k === "Resident" || k === "Resident of Yonkers" ? normalizeNyYesNo(raw) || raw : raw;
      }
    }
    setNyIt2104Fields({ ...emptyNyIt2104Compliance(), ...nyPick });
  }, []);

  const load = useCallback(async (opts) => {
    if (!userId || Number.isNaN(uid)) return;
    const loadSeq = ++profileLoadSeqRef.current;
    setLoading(true);
    setError("");
    const skipHeavyCatalogs = !!opts?.skipHeavyCatalogs && catalogsPrimedRef.current;
    try {
      if (platformMode) {
        const [profRes, orgRes] = await Promise.all([
          getPlatformUserProfile(uid),
          getPlatformOrganizations(),
        ]);
        const bundle = profRes.data;
        setOrgOptions(orgRes.data?.organizations || []);
        const w = bundle.washpro || {};
        setOrganizationId(String(w.organization_id ?? ""));
        setWpUsername(w.username || "");
        setWpDisplay(w.display_name || "");
        setWpActive(!!w.active);
        setWpRoles(
          [...(w.roles || [])].map((c) => String(c || "").trim().toUpperCase()).filter(Boolean),
        );
        setWpPassword("");
        setWashproRoleChoices(
          (bundle.roles_catalog || []).map((r) => ({
            code: String(r.code || "").trim().toUpperCase(),
            name: r.name,
            id: r.id,
          })),
        );
        setHasPayroll(false);
        return;
      }

      if (loadSeq !== profileLoadSeqRef.current) return;

      setComplianceI9({ ...emptyI9() });
      setW4Compliance({ ...emptyW4Compliance() });
      setNyIt2104Fields({ ...emptyNyIt2104Compliance() });

      const [authRes, rRes, gRes, cRes] = await Promise.all([
        getAuthUser(uid),
        getRoles(),
        getGeofences(),
        getEmploymentCategories(),
      ]);
      const auth = authRes.data;
      setWpUsername(auth.username || "");
      setWpDisplay(auth.display_name || "");
      setWpActive(!!auth.active);
      const wpRoleCodes = [...(auth.roles || [])]
        .map((c) => String(c || "").trim().toUpperCase())
        .filter(Boolean);
      setWpRoles(wpRoleCodes);
      setWpPassword("");
      const normalizedWashproChoices = (rRes.data || []).map((r) => ({
        ...r,
        code: String(r.code || "").trim().toUpperCase(),
      }));
      const choiceCodes = new Set(normalizedWashproChoices.map((r) => r.code));
      const orphanWashpro = wpRoleCodes
        .filter((c) => c && !choiceCodes.has(c))
        .map((code) => ({ id: null, code, name: code }));
      setWashproRoleChoices(
        [...normalizedWashproChoices, ...orphanWashpro].sort((a, b) => a.code.localeCompare(b.code)),
      );
      setGeofences(gRes.data || []);
      setCats(cRes.data || []);

      if (!skipHeavyCatalogs) {
        try {
          const [d, j, st, lg, tr] = await Promise.all([
            getOrgHrLookups({ category: "department" }),
            getOrgHrLookups({ category: "job_title" }),
            getOrgHrLookups({ category: "employment_status" }),
            getOrgHrLookups({ category: "language_pref" }),
            getTaRoles().catch(() => ({ data: [] })),
          ]);
          setLkDept(d.data || []);
          setLkJob(j.data || []);
          setLkStatus(st.data || []);
          setLkLang(lg.data || []);
          setTaRoleChoices(tr.data || []);
        } catch {
          setLkDept([]);
          setLkJob([]);
          setLkStatus([]);
          setLkLang([]);
          setTaRoleChoices([]);
        }
        catalogsPrimedRef.current = true;
      }

      let ta = null;
      let hrPayload = null;
      // Fetch payroll + HR for anyone allowed on this page (canUse). Rely on API for auth;
      // ignore 403 on HR during permission/bootstrap edge cases so the rest of the profile can load.
      if (!platformMode && canUse) {
        const [taOutcome, hrOutcome] = await Promise.allSettled([getTaUser(uid), getTaUserHrProfile(uid)]);
        if (taOutcome.status === "fulfilled") {
          ta = taOutcome.value.data;
        } else {
          const st = taOutcome.reason?.response?.status;
          if (st !== 404) throw taOutcome.reason;
        }
        if (hrOutcome.status === "fulfilled") {
          hrPayload = hrOutcome.value.data;
        } else {
          const st = hrOutcome.reason?.response?.status;
          if (st !== 404 && st !== 503 && st !== 403) throw hrOutcome.reason;
        }
      }

      if (loadSeq !== profileLoadSeqRef.current) return;

      if (ta) {
        seedFromTa(ta, auth);
        if (hrPayload && !hrPayload.error) {
          applyHrFromProfile(hrPayload);
        }
      } else {
        setHasPayroll(false);
        const parts = String(auth.display_name || auth.username || "").trim().split(/\s+/);
        setFirstName(parts[0] || "");
        setLastName(parts.slice(1).join(" ") || "");
        setEmail("");
        setGeofenceIds((auth.geofence_ids || []).map(Number));
        const assigns = auth.employment_assignments || [];
        setCatRows(
          assigns.length > 0
            ? assigns.map((a) => ({
                employment_category_id: a.employment_category_id,
                effective_from: String(a.effective_from).slice(0, 10),
                effective_to: a.effective_to ? String(a.effective_to).slice(0, 10) : "",
              }))
            : [
                {
                  employment_category_id: cRes.data?.[0]?.id || "",
                  effective_from: new Date().toISOString().slice(0, 10),
                  effective_to: "",
                },
              ],
        );
      }

      if (!platformMode && uid && !Number.isNaN(uid)) {
        if (localStorage.getItem(`profile_onboard_done_${uid}`) === "1") {
          setOnboardingFreeNav(true);
        }
        const rawStep = localStorage.getItem(`profile_onboard_step_${uid}`);
        if (rawStep != null && rawStep !== "") {
          const n = Number(rawStep);
          if (Number.isFinite(n)) setOnboardMaxStep(Math.max(0, Math.min(5, n)));
        }
      }
    } catch (e) {
      console.error(e);
      if (loadSeq === profileLoadSeqRef.current) {
        setError(e?.response?.data?.error || e?.message || "Load failed");
      }
    } finally {
      if (loadSeq === profileLoadSeqRef.current) {
        setLoading(false);
      }
    }
  }, [userId, uid, platformMode, canUse, seedFromTa, applyHrFromProfile]);

  useEffect(() => {
    if (!canUse) return;
    load();
  }, [canUse, load]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      if (platformMode) {
        const oid = organizationId === "" ? undefined : Number(organizationId);
        const washpro = {
          username: wpUsername.trim(),
          display_name: wpDisplay.trim(),
          active: wpActive,
          roles: wpRoles,
        };
        if (wpPassword.trim()) washpro.password = wpPassword.trim();
        await putPlatformUserProfile(uid, { organization_id: oid, washpro });
        await load();
        return;
      }

      /** Merged `{ payroll, hr, org_settings }` from PUT /hr-profile — reapplied after load() to beat stale GET races. */
      let hrSnapshotFromPut = null;

      const emailTrim = email.trim();
      const mobileDigits = normalizeUsPhoneDigits(mobile);
      const wantsNewProfile =
        !hasPayroll &&
        canTaAdd &&
        firstName.trim() &&
        lastName.trim() &&
        emailTrim &&
        payrollPassword.trim() &&
        roleId;
      const payrollLinkedAfterSave = hasPayroll || wantsNewProfile;
      const payrollBeingSaved = (hasPayroll && canEditPayrollRecords) || wantsNewProfile;

      if (payrollBeingSaved) {
        if (!emailTrim || !isValidEmail(emailTrim)) {
          setError(t("profile.errEmailFmt"));
          return;
        }
        if (!isValidUsPhone10(mobileDigits)) {
          setError(t("profile.errPhone10"));
          return;
        }
      } else {
        if (emailTrim && !isValidEmail(emailTrim)) {
          setError(t("profile.errEmailFmt"));
          return;
        }
        if (mobile && !isValidUsPhone10(mobileDigits)) {
          setError(t("profile.errPhone10"));
          return;
        }
      }
      if (showPayrollTaxIdField) {
        const tinOnly = normalizeTaxIdDigits(itinSsn);
        if (itinSsn && tinOnly.length > 0 && tinOnly.length !== 9) {
          setError(t("profile.errTaxId9"));
          return;
        }
      }

      const dobTrim = profileDob.trim();
      if (payrollBeingSaved && dobTrim && dobTrim >= localDateYmd()) {
        setError(t("profile.errDobFuture"));
        return;
      }

      const formattedAddr = formatPayrollAddressLine(addrLine1, addrApt, addrCity, addrState, addrZip);

      const runEmergencyGate =
        payrollBeingSaved && canEditHrExtras && (workspaceTab === "emergency" || workspaceTab === "documents");
      if (runEmergencyGate) {
        const ec0 = emergency[0];
        const ecPhone = normalizeUsPhoneDigits(ec0?.phone);
        if (!String(ec0?.name || "").trim() || !isValidUsPhone10(ecPhone)) {
          setError(t("profile.errEmergencyRequired"));
          return;
        }
      }
      const runCategoryGate =
        payrollBeingSaved &&
        canEditPayrollRecords &&
        (workspaceTab === "basic" || workspaceTab === "summary");
      if (runCategoryGate && !String(catRows[0]?.employment_category_id || "").trim()) {
        setError(t("profile.errCategoryRequired"));
        return;
      }

      const runComplianceGate =
        payrollBeingSaved && hasPayroll && canEditPayrollRecords && workspaceTab === "compliance";
      if (runComplianceGate && canEditHrExtras) {
        const cErr = validateComplianceForSave({
          firstName,
          lastName,
          addrState,
          complianceI9,
          payrollTaxIdDigits: itinSsn,
          w4Compliance,
          nyIt2104Fields,
          t,
        });
        if (cErr) {
          setError(cErr);
          return;
        }
      }

      const userUpdatePromise = updateUser(uid, {
        username: wpUsername.trim(),
        display_name: wpDisplay.trim(),
        active: wpActive,
        roles: wpRoles,
        password: wpPassword.trim() || undefined,
      });

      if (hasPayroll && canEditPayrollRecords) {
        const taPayload = {
          first_name: firstName,
          last_name: lastName,
          email: emailTrim.toLowerCase(),
          mobile: mobileDigits || null,
          employee_id: employeeId || null,
          address: formattedAddr,
          hire_date: hireDate || null,
          termination_date: termDate || null,
          rehired,
          active: payrollActive,
          role_id: roleId ? Number(roleId) : undefined,
          password: payrollPassword.trim() || undefined,
          rehire_parent_id: rehireParentId === "" ? null : Number(rehireParentId),
          prior_employee_id: priorEmployeeId || null,
        };
        if (showPayrollTaxIdField) {
          const digits = normalizeTaxIdDigits(itinSsn);
          if (digits.length === 9) taPayload.itin_ssn = digits;
        }
        if (deptCode) taPayload.dept_code = deptCode;
        if (jobTitleCode) taPayload.job_title_code = jobTitleCode;
        if (employmentStatusCode) taPayload.employment_status_code = employmentStatusCode;
        if (languageCode) taPayload.language_code = languageCode;
        if (laundryExperience !== "") taPayload.laundry_experience = laundryExperience === "1";
        const geoCat =
          canEditPayrollRecords
            ? [
                putUserGeofences(uid, {
                  geofence_ids: geofenceIds.map(Number),
                  primary_geofence_id: null,
                }),
                putUserEmploymentCategories(uid, {
                  assignments: catRows
                    .filter((r) => r.employment_category_id)
                    .map((r) => ({
                      employment_category_id: Number(r.employment_category_id),
                      effective_from: r.effective_from,
                      effective_to: r.effective_to || null,
                    })),
                }),
              ]
            : [];
        let hrPutBody;
        try {
          hrPutBody = buildHrExtendedPutBody();
          JSON.stringify(hrPutBody);
        } catch (serErr) {
          console.error(serErr);
          setError(t("profile.errSerialize"));
          return;
        }
        const saveResults = await Promise.all([
          userUpdatePromise,
          updateTaUser(uid, taPayload),
          putTaUserHrProfile(uid, hrPutBody),
          ...geoCat,
        ]);
        hrSnapshotFromPut = saveResults[2]?.data ?? null;
      } else {
        await userUpdatePromise;
        if (!hasPayroll && canTaAdd && wantsNewProfile) {
          const createPayload = {
            washpro_user_id: uid,
            first_name: firstName.trim(),
            last_name: lastName.trim(),
            email: emailTrim.toLowerCase(),
            password: payrollPassword.trim(),
            role_id: Number(roleId),
            employee_id: employeeId || null,
            mobile: mobileDigits || null,
            address: formattedAddr,
            hire_date: hireDate || null,
            termination_date: termDate || null,
            rehired,
            active: payrollActive,
            rehire_parent_user_id: rehireParentId === "" ? null : Number(rehireParentId),
            prior_employee_id: priorEmployeeId || null,
          };
          if (showPayrollTaxIdField) {
            const newDigits = normalizeTaxIdDigits(itinSsn);
            if (newDigits.length === 9) createPayload.itin_ssn = newDigits;
          }
          if (deptCode) createPayload.dept_code = deptCode;
          if (jobTitleCode) createPayload.job_title_code = jobTitleCode;
          if (employmentStatusCode) createPayload.employment_status_code = employmentStatusCode;
          if (languageCode) createPayload.language_code = languageCode;
          if (laundryExperience !== "") createPayload.laundry_experience = laundryExperience === "1";
          await createTaUser(createPayload);
          try {
            const hrNewBody = buildHrExtendedPutBody();
            try {
              JSON.stringify(hrNewBody);
            } catch (serErr) {
              console.error(serErr);
              setError(t("profile.errSerialize"));
              return;
            }
            const hrPutRes = await putTaUserHrProfile(uid, hrNewBody);
            hrSnapshotFromPut = hrPutRes?.data ?? null;
          } catch (hrErr) {
            if (hrErr?.response?.status !== 503) throw hrErr;
          }
        }
      }

      if (canEditPayrollRecords && !hasPayroll) {
        await Promise.all([
          putUserGeofences(uid, {
            geofence_ids: geofenceIds.map(Number),
            primary_geofence_id: null,
          }),
          putUserEmploymentCategories(uid, {
            assignments: catRows
              .filter((r) => r.employment_category_id)
              .map((r) => ({
                employment_category_id: Number(r.employment_category_id),
                effective_from: r.effective_from,
                effective_to: r.effective_to || null,
              })),
          }),
        ]);
      }

      await load({ skipHeavyCatalogs: true });

      if (
        !platformMode &&
        hrSnapshotFromPut &&
        hrSnapshotFromPut.hr &&
        !hrSnapshotFromPut.error
      ) {
        try {
          applyHrFromProfile(hrSnapshotFromPut);
        } catch (reapplyErr) {
          console.error(reapplyErr);
          setError(
            reapplyErr?.message ||
              "Saved on the server but the form could not refresh. Reload the page.",
          );
        }
      }

      if (!platformMode && payrollLinkedAfterSave) {
        const wasStrictOnboarding = localStorage.getItem(`profile_onboard_done_${uid}`) !== "1";
        if (wasStrictOnboarding) {
          const ord = ONBOARD_STEP_INDEX[workspaceTab];
          if (ord !== undefined) {
            const raw = localStorage.getItem(`profile_onboard_step_${uid}`);
            const cur = raw != null ? Number(raw) || 0 : 0;
            const next = Math.max(cur, ord + 1);
            localStorage.setItem(`profile_onboard_step_${uid}`, String(next));
            setOnboardMaxStep(next);
          }
        }
        if (workspaceTab === "documents") {
          localStorage.setItem(`profile_onboard_done_${uid}`, "1");
          setOnboardingFreeNav(true);
        }
        if (wasStrictOnboarding && workspaceTab !== "compliance") {
          const stepSnap = Number(localStorage.getItem(`profile_onboard_step_${uid}`)) || 0;
          const start = WORKSPACE_TAB_FLOW.indexOf(workspaceTab);
          if (start >= 0) {
            for (let j = start + 1; j < WORKSPACE_TAB_FLOW.length; j++) {
              const cand = WORKSPACE_TAB_FLOW[j];
              const cord = ONBOARD_STEP_INDEX[cand];
              const linearOk = cand === "summary" || (cord !== undefined && cord <= stepSnap);
              if (!linearOk) continue;
              setWorkspaceTab(cand);
              break;
            }
          }
        }
      }
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function removePayrollProfile() {
    if (!hasPayroll || !canEditPayrollRecords || platformMode) return;
    if (!window.confirm(t("profile.confirmRemovePayroll"))) return;
    setRemovingPayroll(true);
    setError("");
    try {
      await deleteTaUser(uid);
      await load();
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.error || e?.message || "Remove failed");
    } finally {
      setRemovingPayroll(false);
    }
  }

  if (!canUse) {
    return (
      <Box sx={{ p: 2 }}>
        <Alert severity="warning">{t("people.onlyAdmin")}</Alert>
      </Box>
    );
  }

  if (loading) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography>{t("profile.loading")}</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ p: { xs: 1.2, md: 2 }, maxWidth: 900, mx: "auto" }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <IconButton size="small" onClick={() => navigate(platformMode ? "/platform" : "/employees")}>
          <ArrowBack />
        </IconButton>
        <Typography variant="h6" component="h1">
          {platformMode ? t("profile.platformTitle") : t("profile.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
          #{uid}
        </Typography>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>
          {error}
        </Alert>
      ) : null}

      {!platformMode ? (
        <Tabs
          value={workspaceTab}
          onChange={(_, v) => {
            if (isWorkspaceTabLocked(v)) return;
            setWorkspaceTab(v);
          }}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ mb: 2, borderBottom: 1, borderColor: "divider" }}
        >
          {(
            [
              ["summary", t("workspace.tabSummary")],
              ["basic", t("workspace.tabBasic")],
              ["payroll", t("workspace.tabPayroll")],
              ["compliance", t("workspace.tabComplianceData")],
              ["emergency", t("workspace.tabEmergency")],
              ["notes", t("workspace.tabNotes")],
              ["documents", t("workspace.tabDocumentsEvidence")],
            ]
          ).map(([val, label]) => {
            const locked = isWorkspaceTabLocked(val);
            const ord = ONBOARD_STEP_INDEX[val];
            const completed =
              !platformMode &&
              !onboardingFreeNav &&
              ord !== undefined &&
              onboardMaxStep > ord;
            return (
              <Tab
                key={val}
                value={val}
                label={label}
                disabled={locked}
                sx={{
                  ...(locked ? { opacity: 0.45 } : {}),
                  ...(!locked && completed ? { opacity: 0.72, fontWeight: 500, color: "text.secondary" } : {}),
                }}
              />
            );
          })}
        </Tabs>
      ) : null}

      {!platformMode && workspaceTab === "summary" ? (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
            {firstName} {lastName}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {email || "—"} · {mobile || "—"}
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            {t("people.colEmployeeId")}: {employeeId || "—"}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {t("workspace.summaryBlurb")}
          </Typography>
        </Paper>
      ) : null}

      <Stack spacing={2}>
        {platformMode || workspaceTab === "basic" ? (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <ProfileSection
            n={1}
            title={t("profile.sectionLoginSpec")}
            hint={platformMode ? undefined : t("profile.sectionLoginSpecHint")}
          >
            <Stack spacing={1.5}>
              {platformMode ? (
                <FormControl fullWidth size="small">
                  <InputLabel id="org-pick">{t("profile.organization")}</InputLabel>
                  <Select
                    labelId="org-pick"
                    label={t("profile.organization")}
                    value={organizationId}
                    onChange={(e) => setOrganizationId(e.target.value)}
                  >
                    {(orgOptions || []).map((o) => (
                      <MenuItem key={o.id} value={String(o.id)}>
                        {o.display_name || o.slug} (#{o.id})
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              ) : null}
              <TextField
                label={t("people.colUsername")}
                value={wpUsername}
                onChange={(e) => setWpUsername(e.target.value)}
                size="small"
                required
              />
              <TextField
                label={t("profile.newPasswordOptional")}
                type="password"
                value={wpPassword}
                onChange={(e) => setWpPassword(e.target.value)}
                size="small"
              />
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "flex-start" }}>
                <TextField
                  label={t("people.colDisplay")}
                  value={wpDisplay}
                  onChange={(e) => setWpDisplay(e.target.value)}
                  size="small"
                  required={!platformMode}
                  sx={{ flex: 1 }}
                />
                {!platformMode ? (
                  <Button
                    size="small"
                    variant="text"
                    onClick={() => setWpDisplay(`${firstName} ${lastName}`.trim())}
                    disabled={!firstName.trim() && !lastName.trim()}
                    sx={{ mt: { xs: 0, sm: 0.5 } }}
                  >
                    {t("profile.syncDisplayFromLegal")}
                  </Button>
                ) : null}
              </Stack>
              {!platformMode ? (
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                  <TextField
                    label={t("profile.firstName")}
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    size="small"
                    fullWidth
                    required={!!hasPayroll || !!canTaAdd}
                    name="given-name"
                    autoComplete="given-name"
                  />
                  <TextField
                    label={t("profile.lastName")}
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    size="small"
                    fullWidth
                    required={!!hasPayroll || !!canTaAdd}
                    name="family-name"
                    autoComplete="family-name"
                  />
                </Stack>
              ) : null}
              {!platformMode ? (
                <>
                  <TextField
                    label={t("people.colEmail")}
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    size="small"
                    required={!!hasPayroll || !!canTaAdd}
                    helperText={t("profile.loginEmailHint")}
                    name="email"
                    autoComplete="email"
                  />
                  <TextField
                    label={t("profile.phonePrimary")}
                    value={mobile}
                    onChange={(e) => setMobile(normalizeUsPhoneDigits(e.target.value))}
                    size="small"
                    inputProps={{ inputMode: "numeric", maxLength: 10 }}
                    helperText={t("profile.phone10Hint")}
                    name="tel"
                    autoComplete="tel-national"
                  />
                  <TextField
                    select
                    label={t("people.colRole")}
                    value={roleId}
                    onChange={(e) => setRoleId(e.target.value)}
                    size="small"
                    required={!!hasPayroll || !!canTaAdd}
                  >
                    <MenuItem value="">—</MenuItem>
                    {taRoleChoices.map((r) => (
                      <MenuItem key={r.id} value={String(r.id)}>
                        {r.name || r.code}
                      </MenuItem>
                    ))}
                  </TextField>
                  <FormControl fullWidth size="small" required={!!hasPayroll || !!canTaAdd}>
                    <InputLabel id="cat-pick">{t("people.colCategory")}</InputLabel>
                    <Select
                      labelId="cat-pick"
                      label={t("people.colCategory")}
                     value={catRows[0]?.employment_category_id || ""}
                      onChange={(e) => {
                        const v = e.target.value;
                        setCatRows((prev) => {
                          const next = [...prev];
                          if (!next.length) {
                            next.push({
                              employment_category_id: v,
                              effective_from: new Date().toISOString().slice(0, 10),
                              effective_to: "",
                            });
                            return next;
                          }
                          next[0] = { ...next[0], employment_category_id: v };
                          return next;
                        });
                      }}
                    >
                      <MenuItem value="">—</MenuItem>
                      {cats.map((c) => (
                        <MenuItem key={c.id} value={String(c.id)}>
                          {c.name}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </>
              ) : null}
              <FormControl fullWidth size="small">
                <InputLabel id="roles-pick">{t("profile.washproRoles")}</InputLabel>
                <Select
                  labelId="roles-pick"
                  multiple
                  label={t("profile.washproRoles")}
                  value={wpRoles}
                  onChange={(e) =>
                    setWpRoles(typeof e.target.value === "string" ? e.target.value.split(",") : e.target.value)
                  }
                  input={<OutlinedInput label={t("profile.washproRoles")} />}
                  renderValue={(sel) => sel.join(", ")}
                >
                  {washproRoleChoices.map((r) => (
                    <MenuItem key={r.code} value={r.code}>
                      {r.code}
                      {r.name && r.name !== r.code ? ` — ${r.name}` : ""}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControlLabel
                control={<Checkbox checked={wpActive} onChange={(e) => setWpActive(e.target.checked)} />}
                label={t("common.active")}
              />
            </Stack>
          </ProfileSection>
          {!platformMode ? (
            <Accordion
              defaultExpanded={false}
              disableGutters
              elevation={0}
              sx={{
                mt: 2,
                border: "1px solid",
                borderColor: "divider",
                borderRadius: 1,
                "&:before": { display: "none" },
              }}
            >
              <AccordionSummary expandIcon={<ExpandMore />}>
                <Typography sx={{ fontWeight: 700 }}>{t("profile.sectionAdvancedAssignments")}</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Stack spacing={2} sx={{ pt: 0.5 }}>
                  <Box>
                    <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                        {t("profile.sectionEmployment")}
                      </Typography>
                      {canEditPayrollRecords ? (
                        <Button
                          size="small"
                          startIcon={<Add />}
                          onClick={() =>
                            setCatRows([
                              ...catRows,
                              {
                                employment_category_id: "",
                                effective_from: new Date().toISOString().slice(0, 10),
                                effective_to: "",
                              },
                            ])
                          }
                        >
                          {t("profile.addEmploymentRow")}
                        </Button>
                      ) : null}
                    </Stack>
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                      {t("profile.sectionEmploymentAdvancedHint")}
                    </Typography>
                    {(catRows || []).length < 2 ? (
                      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                        {t("profile.categoryHistoryEmpty")}
                      </Typography>
                    ) : null}
                    {(catRows || []).slice(1).map((row, i) => {
                      const idx = i + 1;
                      return (
                        <Stack
                          key={idx}
                          direction={{ xs: "column", sm: "row" }}
                          spacing={1}
                          alignItems={{ sm: "center" }}
                          sx={{ mb: 1 }}
                        >
                          <TextField
                            select
                            label={t("people.colCategory")}
                            value={row.employment_category_id}
                            onChange={(e) => {
                              const next = [...catRows];
                              next[idx] = { ...next[idx], employment_category_id: e.target.value };
                              setCatRows(next);
                            }}
                            size="small"
                            sx={{ minWidth: 200 }}
                            disabled={!canEditPayrollRecords}
                          >
                            <MenuItem value="">—</MenuItem>
                            {cats.map((c) => (
                              <MenuItem key={c.id} value={String(c.id)}>
                                {c.name}
                              </MenuItem>
                            ))}
                          </TextField>
                          <TextField
                            type="date"
                            label="From"
                            InputLabelProps={{ shrink: true }}
                            value={row.effective_from || ""}
                            onChange={(e) => {
                              const next = [...catRows];
                              next[idx] = { ...next[idx], effective_from: e.target.value };
                              setCatRows(next);
                            }}
                            size="small"
                            disabled={!canEditPayrollRecords}
                          />
                          <TextField
                            type="date"
                            label="To"
                            InputLabelProps={{ shrink: true }}
                            value={row.effective_to || ""}
                            onChange={(e) => {
                              const next = [...catRows];
                              next[idx] = { ...next[idx], effective_to: e.target.value };
                              setCatRows(next);
                            }}
                            size="small"
                            disabled={!canEditPayrollRecords}
                          />
                          {canEditPayrollRecords ? (
                            <IconButton
                              aria-label={t("profile.removeEmploymentRow")}
                              onClick={() => setCatRows(catRows.filter((_, j) => j !== idx))}
                            >
                              <DeleteOutline />
                            </IconButton>
                          ) : null}
                        </Stack>
                      );
                    })}
                  </Box>
                </Stack>
              </AccordionDetails>
            </Accordion>
          ) : null}
        </Paper>
        ) : null}

        {platformMode ? (
          <Alert severity="info" variant="outlined">
            {t("profile.platformLoginOnly")}
          </Alert>
        ) : null}

        {!platformMode && workspaceTab === "payroll" ? (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <ProfileSection n={2} title={t("profile.sectionPayrollSpec")} hint={t("profile.sectionPayrollSpecHint")}>
            {hasPayroll && (canTaView || canEditPayrollRecords) ? (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                {t("profile.formsLiveInSection5")}
              </Typography>
            ) : null}
            {!hasPayroll ? (
              <Alert severity="info" sx={{ mb: 1 }}>
                {t("profile.noPayrollYet")}
              </Alert>
            ) : null}
            <Stack spacing={1.5}>
            <Typography variant="caption" color="text.secondary">
              {t("profile.basicPayrollDupContact")}
            </Typography>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                label={t("profile.firstName")}
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                size="small"
                fullWidth
                required={!!hasPayroll || !!canTaAdd}
                disabled={!canEditHrExtras}
                name="given-name"
                autoComplete="given-name"
              />
              <TextField
                label={t("profile.lastName")}
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                size="small"
                fullWidth
                required={!!hasPayroll || !!canTaAdd}
                disabled={!canEditHrExtras}
                name="family-name"
                autoComplete="family-name"
              />
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                label={t("profile.middleInitial")}
                value={middleInitial}
                onChange={(e) => setMiddleInitial(e.target.value.slice(0, 1))}
                size="small"
                inputProps={{ maxLength: 1 }}
                sx={{ maxWidth: 120 }}
                disabled={!canEditHrExtras}
                name="additional-name"
                autoComplete="additional-name"
              />
              <TextField
                label={t("profile.otherLastName")}
                value={otherLastName}
                onChange={(e) => setOtherLastName(e.target.value)}
                size="small"
                fullWidth
                disabled={!canEditHrExtras}
                name="previous-family-name"
                autoComplete="off"
                helperText={t("profile.otherLastNameHint")}
              />
            </Stack>
            <TextField
              label={t("profile.dateOfBirth")}
              type="date"
              value={profileDob}
              onChange={(e) => setProfileDob(e.target.value)}
              InputLabelProps={{ shrink: true }}
              inputProps={{ max: localDateYmd() }}
              size="small"
              fullWidth
              disabled={!canEditHrExtras}
            />
            <TextField
              label={t("profile.payrollPasswordHint")}
              type="password"
              value={payrollPassword}
              onChange={(e) => setPayrollPassword(e.target.value)}
              size="small"
              disabled={!canEditHrExtras}
              helperText={hasPayroll ? t("profile.payrollPasswordEdit") : t("profile.payrollPasswordCreate")}
            />
            <TextField
              label={t("profile.employeeId")}
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
              size="small"
              InputProps={{ readOnly: !!hasPayroll }}
              helperText={hasPayroll ? t("profile.employeeIdReadOnlyHint") : undefined}
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <FormControl fullWidth size="small" disabled={!canEditPayrollRecords}>
                <InputLabel>{t("people.filterDepartment")}</InputLabel>
                <Select
                  label={t("people.filterDepartment")}
                  value={deptCode}
                  onChange={(e) => setDeptCode(e.target.value)}
                >
                  <MenuItem value="">—</MenuItem>
                  {lkDept.map((r) => (
                    <MenuItem key={r.id} value={String(r.code)}>
                      {r.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" disabled={!canEditPayrollRecords}>
                <InputLabel>{t("profile.jobTitle")}</InputLabel>
                <Select
                  label={t("profile.jobTitle")}
                  value={jobTitleCode}
                  onChange={(e) => {
                    const code = e.target.value;
                    setJobTitleCode(code);
                    if (!code) {
                      setJobTitle("");
                      return;
                    }
                    const row = lkJob.find((x) => String(x.code) === String(code));
                    setJobTitle(row?.label || "");
                  }}
                >
                  <MenuItem value="">—</MenuItem>
                  {lkJob.map((r) => (
                    <MenuItem key={r.id} value={String(r.code)}>
                      {r.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <FormControl fullWidth size="small" disabled={!canEditPayrollRecords}>
                <InputLabel>{t("people.filterStatus")}</InputLabel>
                <Select
                  label={t("people.filterStatus")}
                  value={employmentStatusCode}
                  onChange={(e) => setEmploymentStatusCode(e.target.value)}
                >
                  <MenuItem value="">—</MenuItem>
                  {lkStatus.map((r) => (
                    <MenuItem key={r.id} value={String(r.code)}>
                      {r.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" disabled={!canEditPayrollRecords}>
                <InputLabel>{t("profile.languagePreference")}</InputLabel>
                <Select
                  label={t("profile.languagePreference")}
                  value={languageCode}
                  onChange={(e) => {
                    const code = e.target.value;
                    setLanguageCode(code);
                    if (!code) {
                      setLanguagePreference("");
                      return;
                    }
                    const row = lkLang.find((x) => String(x.code) === String(code));
                    setLanguagePreference(row?.label || code || "");
                  }}
                >
                  <MenuItem value="">—</MenuItem>
                  {lkLang.map((r) => (
                    <MenuItem key={r.id} value={String(r.code)}>
                      {r.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl fullWidth size="small" disabled={!canEditPayrollRecords}>
                <InputLabel>{t("profile.laundryExperience")}</InputLabel>
                <Select
                  label={t("profile.laundryExperience")}
                  value={laundryExperience}
                  onChange={(e) => setLaundryExperience(e.target.value)}
                >
                  <MenuItem value="">—</MenuItem>
                  <MenuItem value="1">{t("common.yes")}</MenuItem>
                  <MenuItem value="0">{t("common.no")}</MenuItem>
                </Select>
              </FormControl>
            </Stack>
            <TextField label={t("profile.supervisorName")} value={supervisorName} onChange={(e) => setSupervisorName(e.target.value)} size="small" fullWidth disabled={!canEditHrExtras} />
            <Typography variant="caption" color="text.secondary" display="block">
              {t("profile.mailingAddressHint")}
              {!hasPayrollMaps ? (
                <>
                  {" "}
                  {t("profile.mapsKeyMissing")}
                </>
              ) : null}
            </Typography>
            <TextField
              inputRef={payrollStreetRef}
              label={t("organization.employerStreet")}
              value={addrLine1}
              onChange={(e) => setAddrLine1(e.target.value)}
              size="small"
              fullWidth
              required={!!hasPayroll || !!canTaAdd}
              disabled={!canEditHrExtras}
              name="street-address"
              autoComplete="street-address"
            />
            <TextField
              label={t("organization.employerApt")}
              value={addrApt}
              onChange={(e) => setAddrApt(e.target.value)}
              size="small"
              fullWidth
              disabled={!canEditHrExtras}
              name="address-line2"
              autoComplete="address-line2"
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                label={t("hr.city")}
                value={addrCity}
                onChange={(e) => setAddrCity(e.target.value)}
                size="small"
                fullWidth
                required={!!hasPayroll || !!canTaAdd}
                disabled={!canEditHrExtras}
                name="address-level2"
                autoComplete="address-level2"
              />
              <TextField
                label={t("hr.state")}
                value={addrState}
                onChange={(e) => setAddrState(e.target.value)}
                size="small"
                fullWidth
                required={!!hasPayroll || !!canTaAdd}
                disabled={!canEditHrExtras}
                inputProps={{ maxLength: 2, style: { textTransform: "uppercase" } }}
                name="address-level1"
                autoComplete="address-level1"
              />
              <TextField
                label={t("hr.zip")}
                value={addrZip}
                onChange={(e) => setAddrZip(e.target.value)}
                size="small"
                fullWidth
                required={!!hasPayroll || !!canTaAdd}
                disabled={!canEditHrExtras}
                inputProps={{ inputMode: "numeric" }}
                name="postal-code"
                autoComplete="postal-code"
              />
            </Stack>
            {showPayrollTaxIdField ? (
              <TextField
                label={t("profile.taxId")}
                value={itinSsn}
                onChange={(e) => setItinSsn(normalizeTaxIdDigits(e.target.value))}
                size="small"
                inputProps={{ maxLength: 9, inputMode: "numeric" }}
                fullWidth
                autoComplete="off"
                disabled={!canEditHrExtras}
                name="tin-ssn"
                helperText={
                  itinLast4Hint && normalizeTaxIdDigits(itinSsn).length !== 9
                    ? t("profile.taxIdMaskedHint").replace("{mask}", `***-**-${itinLast4Hint}`)
                    : t("profile.taxIdHelp")
                }
              />
            ) : (
              <Typography variant="body2" color="text.secondary">
                {t("profile.taxIdW2ComplianceOnly")}
              </Typography>
            )}
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                label={t("profile.hireDate")}
                type="date"
                InputLabelProps={{ shrink: true }}
                value={hireDate}
                onChange={(e) => setHireDate(e.target.value)}
                size="small"
                fullWidth
                disabled={!canEditPayrollRecords}
              />
              <TextField
                label={t("profile.termDate")}
                type="date"
                InputLabelProps={{ shrink: true }}
                value={termDate}
                onChange={(e) => setTermDate(e.target.value)}
                size="small"
                fullWidth
                disabled={!canEditPayrollRecords}
              />
            </Stack>
            <TextField
              label={t("people.rehireFrom")}
              value={rehireParentId}
              onChange={(e) => setRehireParentId(e.target.value)}
              size="small"
              disabled={!canEditPayrollRecords}
              helperText={t("profile.rehireParentHint")}
            />
            <TextField
              label={t("people.priorEmpId")}
              value={priorEmployeeId}
              onChange={(e) => setPriorEmployeeId(e.target.value)}
              size="small"
              disabled={!canEditPayrollRecords}
            />
            <FormControlLabel
              control={
                <Checkbox
                  checked={rehired}
                  onChange={(e) => setRehired(e.target.checked)}
                  disabled={!canEditPayrollRecords}
                />
              }
              label="Rehired"
            />
            {rehired ? (
              <TextField
                label={t("profile.rehireStartDate")}
                type="date"
                InputLabelProps={{ shrink: true }}
                value={rehireStartDate}
                onChange={(e) => setRehireStartDate(e.target.value)}
                size="small"
                fullWidth
                disabled={!canEditHrExtras}
              />
            ) : null}
            <FormControlLabel
              control={
                <Checkbox
                  checked={payrollActive}
                  onChange={(e) => setPayrollActive(e.target.checked)}
                  disabled={!canEditPayrollRecords}
                />
              }
              label={t("profile.payrollRecordActive")}
            />
            <Typography variant="subtitle2" sx={{ fontWeight: 600, pt: 1 }}>
              {t("profile.sectionGeofences")}
            </Typography>
            <FormControl fullWidth size="small" sx={{ mb: 1 }}>
              <InputLabel id="gf-m">{t("profile.sectionGeofences")}</InputLabel>
              <Select
                labelId="gf-m"
                multiple
                value={geofenceIds}
                onChange={(e) => {
                  const raw = e.target.value;
                  setGeofenceIds((typeof raw === "string" ? raw.split(",") : raw).map(Number));
                }}
                input={<OutlinedInput label={t("profile.sectionGeofences")} />}
                disabled={!canEditPayrollRecords}
                renderValue={(selected) =>
                  selected.map((id) => geofences.find((g) => Number(g.id) === Number(id))?.name || id).join(", ")
                }
              >
                {geofences.map((g) => (
                  <MenuItem key={g.id} value={g.id}>
                    {g.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {hasPayroll && canEditPayrollRecords ? (
              <Button
                variant="outlined"
                color="inherit"
                startIcon={<DeleteOutline />}
                onClick={removePayrollProfile}
                disabled={removingPayroll}
                sx={{ alignSelf: "flex-start", borderColor: "divider", color: "text.secondary" }}
              >
                {removingPayroll ? t("common.saving") : t("profile.removePayrollProfile")}
              </Button>
            ) : null}
          </Stack>
          </ProfileSection>
        </Paper>
        ) : null}

        {!platformMode && workspaceTab === "compliance" && (canTaView || canEditPayrollRecords) && (hasPayroll || canTaAdd) ? (
          <Paper variant="outlined" sx={{ p: 2 }}>
            <ProfileSection title={t("workspace.tabComplianceData")} hint={t("workspace.complianceDataIntro")}>
              <Stack spacing={1}>
                <Accordion defaultExpanded disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}>
                  <AccordionSummary expandIcon={<ExpandMore />}>
                    <Typography sx={{ fontWeight: 600 }}>{t("hr.i9BlockTitle")}</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <I9DetailsForm
                      i9={complianceI9}
                      setI9={setComplianceI9}
                      canEdit={canEditHrExtras}
                      omitIdentityFields
                      streetAutocompleteEnabled={mapsForComplianceTab}
                      payrollTaxIdDigits={itinSsn}
                      onPayrollTaxIdDigitsChange={setItinSsn}
                    />
                  </AccordionDetails>
                </Accordion>
                <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}>
                  <AccordionSummary expandIcon={<ExpandMore />}>
                    <Typography sx={{ fontWeight: 600 }}>{t("profile.complianceW4Title")}</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Stack spacing={1.5}>
                      <Typography variant="caption" color="text.secondary">
                        {t("profile.complianceW4Hint")}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block">
                        {t("profile.w4EmployeeStep3Hint")}
                      </Typography>
                      {canWashproUserAdmin ? (
                        <Typography variant="caption" color="text.secondary" display="block">
                          {t("profile.w4AdminRatesHint")}
                        </Typography>
                      ) : null}
                      <TextField
                        label={t("profile.w4TaxYear")}
                        type="number"
                        value={w4Compliance.w4_tax_year || ""}
                        onChange={(e) =>
                          setW4Compliance((s) => ({ ...s, w4_tax_year: String(e.target.value).slice(0, 4) }))
                        }
                        size="small"
                        disabled={!canEditHrExtras}
                        inputProps={{ min: 2020, max: 2099 }}
                      />
                      <FormControl fullWidth size="small" required>
                        <InputLabel id="w4-fs">{t("profile.w4FilingStatus")}</InputLabel>
                        <Select
                          labelId="w4-fs"
                          label={t("profile.w4FilingStatus")}
                          value={
                            w4Compliance.is_nonresident_alien
                              ? "single_or_mfs"
                              : w4Compliance.filing_status || ""
                          }
                          onChange={(e) => setW4Compliance((s) => ({ ...s, filing_status: e.target.value }))}
                          disabled={!canEditHrExtras || w4Compliance.is_nonresident_alien}
                          displayEmpty
                        >
                          <MenuItem value="">—</MenuItem>
                          <MenuItem value="single_or_mfs">{t("profile.w4FsSingleOrMfs")}</MenuItem>
                          <MenuItem value="mfj_or_qss">{t("profile.w4FsMfjOrQss")}</MenuItem>
                          <MenuItem value="hoh">{t("profile.w4FsHead")}</MenuItem>
                        </Select>
                      </FormControl>
                      {canWashproUserAdmin ? (
                        <FormControlLabel
                          control={
                            <Checkbox
                              checked={!!w4Compliance.is_nonresident_alien}
                              onChange={(e) => {
                                const on = e.target.checked;
                                setW4Compliance((s) => ({
                                  ...s,
                                  is_nonresident_alien: on,
                                  exempt: on ? false : s.exempt,
                                  filing_status: on ? "single_or_mfs" : s.filing_status,
                                  nra_allow_step3_4: on ? s.nra_allow_step3_4 : false,
                                }));
                              }}
                              disabled={!canEditHrExtras}
                            />
                          }
                          label={t("profile.w4NonresidentAlien")}
                        />
                      ) : null}
                      {w4Compliance.is_nonresident_alien && canWashproUserAdmin ? (
                        <FormControlLabel
                          control={
                            <Checkbox
                              checked={!!w4Compliance.nra_allow_step3_4}
                              onChange={(e) =>
                                setW4Compliance((s) => ({ ...s, nra_allow_step3_4: e.target.checked }))
                              }
                              disabled={!canEditHrExtras}
                            />
                          }
                          label={t("profile.w4NraAllowStep34")}
                        />
                      ) : null}
                      <FormControl fullWidth size="small">
                        <InputLabel id="w4-mj">{t("profile.w4Step2MultipleJobs")}</InputLabel>
                        <Select
                          labelId="w4-mj"
                          label={t("profile.w4Step2MultipleJobs")}
                          value={w4Compliance.step2_multiple_jobs || ""}
                          onChange={(e) => {
                            const v = e.target.value;
                            setW4Compliance((s) => ({
                              ...s,
                              step2_multiple_jobs: v,
                              two_jobs_only: v === "no" ? false : s.two_jobs_only,
                            }));
                          }}
                          disabled={!canEditHrExtras || w4Compliance.exempt}
                          displayEmpty
                        >
                          <MenuItem value="">
                            <em>{t("common.optional")}</em>
                          </MenuItem>
                          <MenuItem value="yes">{t("common.yes")}</MenuItem>
                          <MenuItem value="no">{t("common.no")}</MenuItem>
                        </Select>
                      </FormControl>
                      <FormControlLabel
                        control={
                          <Checkbox
                            checked={!!w4Compliance.two_jobs_only}
                            onChange={(e) => setW4Compliance((s) => ({ ...s, two_jobs_only: e.target.checked }))}
                            disabled={
                              !canEditHrExtras ||
                              w4Compliance.exempt ||
                              w4Compliance.step2_multiple_jobs === "no"
                            }
                          />
                        }
                        label={t("profile.w4TwoJobs")}
                      />
                      <FormControlLabel
                        control={
                          <Checkbox
                            checked={!!w4Compliance.exempt}
                            onChange={(e) => {
                              const on = e.target.checked;
                              setW4Compliance((s) => ({
                                ...s,
                                exempt: on,
                                ...(on
                                  ? {
                                      two_jobs_only: false,
                                      step2_multiple_jobs: "",
                                      w4_qualifying_children_under_17_count: "0",
                                      w4_other_dependents_count: "0",
                                      w4_helper_children_under_17: "0",
                                      w4_helper_other_dependents: "0",
                                      w4_step3_other_credits_amount: "",
                                      step3a_amount: "",
                                      step3b_amount: "",
                                      dependents_amount: "",
                                      w4_step3_use_auto_calculation: true,
                                      w4_step3_manual_override: false,
                                      other_income: "",
                                      deductions: "",
                                      extra_withholding: "",
                                    }
                                  : {}),
                              }));
                            }}
                            disabled={!canEditHrExtras || w4Compliance.is_nonresident_alien}
                          />
                        }
                        label={t("profile.w4Exempt")}
                      />
                      <Typography variant="caption" color="text.secondary">
                        {t("profile.w4HelperCountsHint")}
                      </Typography>
                      <FormControlLabel
                        control={
                          <Checkbox
                            checked={!!w4Compliance.w4_step3_use_auto_calculation}
                            onChange={(e) =>
                              setW4Compliance((s) => ({
                                ...s,
                                w4_step3_use_auto_calculation: e.target.checked,
                                ...(e.target.checked ? { w4_step3_manual_override: false } : {}),
                              }))
                            }
                            disabled={
                              !canEditHrExtras ||
                              w4Compliance.exempt ||
                              (w4Compliance.is_nonresident_alien && !w4Compliance.nra_allow_step3_4)
                            }
                          />
                        }
                        label={t("profile.w4Step3AutoCalc")}
                      />
                      <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                        <TextField
                          label={t("profile.w4QualifyingChildrenCount")}
                          type="number"
                          value={w4Compliance.w4_qualifying_children_under_17_count ?? ""}
                          onChange={(e) => {
                            const v = e.target.value;
                            setW4Compliance((s) => ({
                              ...s,
                              w4_qualifying_children_under_17_count: v,
                              w4_helper_children_under_17: v,
                            }));
                          }}
                          size="small"
                          disabled={
                            !canEditHrExtras ||
                            w4Compliance.exempt ||
                            (w4Compliance.is_nonresident_alien && !w4Compliance.nra_allow_step3_4)
                          }
                          inputProps={{ min: 0, step: 1 }}
                        />
                        <TextField
                          label={t("profile.w4OtherDependentsCount")}
                          type="number"
                          value={w4Compliance.w4_other_dependents_count ?? ""}
                          onChange={(e) => {
                            const v = e.target.value;
                            setW4Compliance((s) => ({
                              ...s,
                              w4_other_dependents_count: v,
                              w4_helper_other_dependents: v,
                            }));
                          }}
                          size="small"
                          disabled={
                            !canEditHrExtras ||
                            w4Compliance.exempt ||
                            (w4Compliance.is_nonresident_alien && !w4Compliance.nra_allow_step3_4)
                          }
                          inputProps={{ min: 0, step: 1 }}
                        />
                      </Stack>
                      <TextField
                        label={t("profile.w4Step3OtherCredits")}
                        value={w4Compliance.step3_other_credits_amount}
                        onChange={(e) =>
                          setW4Compliance((s) => ({ ...s, step3_other_credits_amount: e.target.value }))
                        }
                        size="small"
                        disabled={
                          !canEditHrExtras ||
                          w4Compliance.exempt ||
                          (w4Compliance.is_nonresident_alien && !w4Compliance.nra_allow_step3_4) ||
                          w4TaxSettings?.w4_allow_other_credits === 0 ||
                          w4TaxSettings?.w4_allow_other_credits === false
                        }
                      />
                      <TextField
                        label={t("profile.w4HelperTotalDeps")}
                        value={w4Compliance.w4_helper_total_dependents}
                        onChange={(e) =>
                          setW4Compliance((s) => ({ ...s, w4_helper_total_dependents: e.target.value }))
                        }
                        size="small"
                        disabled={!canEditHrExtras}
                        helperText={t("profile.w4HelperTotalDepsHint")}
                      />
                      {canWashproUserAdmin &&
                      w4TaxSettings &&
                      (w4TaxSettings.w4_enable_manual_override === 1 ||
                        w4TaxSettings.w4_enable_manual_override === true) ? (
                        <>
                          <FormControlLabel
                            control={
                              <Checkbox
                                checked={!!w4Compliance.w4_step3_manual_override}
                                onChange={(e) =>
                                  setW4Compliance((s) => ({
                                    ...s,
                                    w4_step3_manual_override: e.target.checked,
                                    w4_step3_use_auto_calculation: e.target.checked
                                      ? false
                                      : s.w4_step3_use_auto_calculation,
                                  }))
                                }
                                disabled={
                                  !canEditHrExtras ||
                                  w4Compliance.exempt ||
                                  (w4Compliance.is_nonresident_alien && !w4Compliance.nra_allow_step3_4)
                                }
                              />
                            }
                            label={t("profile.w4Step3ManualOverride")}
                          />
                          <TextField
                            label={t("profile.w4Step3OverrideReason")}
                            value={w4Compliance.w4_step3_override_reason || ""}
                            onChange={(e) =>
                              setW4Compliance((s) => ({ ...s, w4_step3_override_reason: e.target.value }))
                            }
                            size="small"
                            disabled={!canEditHrExtras || !w4Compliance.w4_step3_manual_override}
                          />
                        </>
                      ) : null}
                      {w4Compliance.w4_step3_use_auto_calculation && !w4Compliance.w4_step3_manual_override ? (
                        <Alert severity="info" variant="outlined" sx={{ py: 0.75 }}>
                          <Typography variant="caption" component="div">
                            {t("profile.w4Step3PreviewIntro", {
                              year: w4Compliance.w4_tax_year || new Date().getFullYear(),
                            })}
                          </Typography>
                          <Typography variant="caption" component="div" sx={{ display: "block", mt: 0.5 }}>
                            {t("profile.w4Step3PreviewLines", {
                              a: w4Step3Preview.a,
                              b: w4Step3Preview.b,
                              t: w4Step3Preview.t,
                              rc: w4Step3Preview.rateC,
                              ro: w4Step3Preview.rateO,
                            })}
                          </Typography>
                          {(w4Compliance.step3a_amount ||
                            w4Compliance.step3b_amount ||
                            w4Compliance.dependents_amount) &&
                          w4Compliance.w4_calc_method ? (
                            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                              {t("profile.w4Step3LastSaved", {
                                m: w4Compliance.w4_calc_method || "—",
                                ts: w4Compliance.w4_calc_timestamp
                                  ? String(w4Compliance.w4_calc_timestamp).slice(0, 19)
                                  : "—",
                              })}
                            </Typography>
                          ) : null}
                        </Alert>
                      ) : null}
                      {(!w4Compliance.w4_step3_use_auto_calculation || w4Compliance.w4_step3_manual_override) &&
                      !w4Compliance.exempt &&
                      (!w4Compliance.is_nonresident_alien || w4Compliance.nra_allow_step3_4) ? (
                        <>
                          <TextField
                            label={t("profile.w4Step3a")}
                            value={w4Compliance.step3a_amount}
                            onChange={(e) =>
                              setW4Compliance((s) => ({ ...s, step3a_amount: e.target.value }))
                            }
                            size="small"
                            disabled={
                              !canEditHrExtras ||
                              (w4Compliance.w4_step3_use_auto_calculation &&
                                !w4Compliance.w4_step3_manual_override)
                            }
                          />
                          <TextField
                            label={t("profile.w4Step3b")}
                            value={w4Compliance.step3b_amount}
                            onChange={(e) =>
                              setW4Compliance((s) => ({ ...s, step3b_amount: e.target.value }))
                            }
                            size="small"
                            disabled={
                              !canEditHrExtras ||
                              (w4Compliance.w4_step3_use_auto_calculation &&
                                !w4Compliance.w4_step3_manual_override)
                            }
                          />
                          <TextField
                            label={t("profile.w4Step3Total")}
                            value={w4Compliance.dependents_amount}
                            onChange={(e) =>
                              setW4Compliance((s) => ({ ...s, dependents_amount: e.target.value }))
                            }
                            size="small"
                            disabled={
                              !canEditHrExtras ||
                              (w4Compliance.w4_step3_use_auto_calculation &&
                                !w4Compliance.w4_step3_manual_override)
                            }
                            helperText={t("profile.w4Step3TotalHint")}
                          />
                        </>
                      ) : null}
                      <TextField
                        label={t("profile.w4OtherIncome")}
                        value={w4Compliance.other_income}
                        onChange={(e) => setW4Compliance((s) => ({ ...s, other_income: e.target.value }))}
                        size="small"
                        disabled={
                          !canEditHrExtras ||
                          w4Compliance.exempt ||
                          (w4Compliance.is_nonresident_alien && !w4Compliance.nra_allow_step3_4)
                        }
                      />
                      <TextField
                        label={t("profile.w4Deductions")}
                        value={w4Compliance.deductions}
                        onChange={(e) => setW4Compliance((s) => ({ ...s, deductions: e.target.value }))}
                        size="small"
                        disabled={
                          !canEditHrExtras ||
                          w4Compliance.exempt ||
                          (w4Compliance.is_nonresident_alien && !w4Compliance.nra_allow_step3_4)
                        }
                      />
                      <TextField
                        label={t("profile.w4ExtraWithholding")}
                        value={w4Compliance.extra_withholding}
                        onChange={(e) =>
                          setW4Compliance((s) => ({ ...s, extra_withholding: e.target.value }))
                        }
                        size="small"
                        disabled={
                          !canEditHrExtras ||
                          w4Compliance.exempt ||
                          (w4Compliance.is_nonresident_alien && !w4Compliance.nra_allow_step3_4)
                        }
                      />
                    </Stack>
                  </AccordionDetails>
                </Accordion>
                <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}>
                  <AccordionSummary expandIcon={<ExpandMore />}>
                    <Typography sx={{ fontWeight: 600 }}>{t("profile.complianceNyItTitle")}</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Stack spacing={1.5}>
                      <Typography variant="caption" color="text.secondary">
                        {t("profile.complianceNyItHint")}
                      </Typography>
                      <Alert severity="info" variant="outlined" sx={{ py: 0.5 }}>
                        <Typography variant="caption" display="block">
                          {t("profile.nyItStatusFromW4")}
                          {w4Compliance.filing_status
                            ? ` (${nyIt2104StatusFromW4Filing(w4Compliance.filing_status) || "—"})`
                            : ""}
                        </Typography>
                      </Alert>
                      <FormControl
                        fullWidth
                        size="small"
                        disabled={!canEditHrExtras}
                        required={String(addrState || "").trim().toUpperCase() === "NY"}
                      >
                        <InputLabel id="ny-nyc">{t("profile.nyNycResident")}</InputLabel>
                        <Select
                          labelId="ny-nyc"
                          label={t("profile.nyNycResident")}
                          value={normalizeNyYesNo(nyIt2104Fields.Resident)}
                          onChange={(e) => {
                            const v = e.target.value;
                            setNyIt2104Fields((s) => {
                              const next = { ...s, Resident: v };
                              if (v === "Yes") next["Resident of Yonkers"] = "No";
                              return next;
                            });
                          }}
                        >
                          <MenuItem value="">
                            <em>—</em>
                          </MenuItem>
                          <MenuItem value="Yes">{t("common.yes")}</MenuItem>
                          <MenuItem value="No">{t("common.no")}</MenuItem>
                        </Select>
                      </FormControl>
                      <FormControl
                        fullWidth
                        size="small"
                        disabled={!canEditHrExtras}
                        required={String(addrState || "").trim().toUpperCase() === "NY"}
                      >
                        <InputLabel id="ny-yon">{t("profile.nyYonkersResident")}</InputLabel>
                        <Select
                          labelId="ny-yon"
                          label={t("profile.nyYonkersResident")}
                          value={normalizeNyYesNo(nyIt2104Fields["Resident of Yonkers"])}
                          onChange={(e) => {
                            const v = e.target.value;
                            setNyIt2104Fields((s) => {
                              const next = { ...s, "Resident of Yonkers": v };
                              if (v === "Yes") next.Resident = "No";
                              return next;
                            });
                          }}
                        >
                          <MenuItem value="">
                            <em>—</em>
                          </MenuItem>
                          <MenuItem value="Yes">{t("common.yes")}</MenuItem>
                          <MenuItem value="No">{t("common.no")}</MenuItem>
                        </Select>
                      </FormControl>
                      {["line 1", "line 2", "line 3"].map((k) => (
                        <TextField
                          key={k}
                          label={k}
                          value={nyIt2104Fields[k] || ""}
                          onChange={(e) => setNyIt2104Fields((s) => ({ ...s, [k]: e.target.value }))}
                          size="small"
                          disabled={!canEditHrExtras}
                        />
                      ))}
                    </Stack>
                  </AccordionDetails>
                </Accordion>
                <Accordion disableGutters elevation={0} sx={{ border: "1px solid", borderColor: "divider", borderRadius: 1, "&:before": { display: "none" } }}>
                  <AccordionSummary expandIcon={<ExpandMore />}>
                    <Typography sx={{ fontWeight: 600 }}>{t("profile.complianceNyLsTitle")}</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      {t("profile.complianceNyLsBlurb")}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t("profile.complianceNyLsPayNotice")}
                    </Typography>
                    <Button sx={{ mt: 1 }} size="small" variant="outlined" onClick={() => navigate(`/employees/${uid}/hr`)}>
                      {t("profile.openEmployeeFormsWorkspace")}
                    </Button>
                  </AccordionDetails>
                </Accordion>
              </Stack>
            </ProfileSection>
          </Paper>
        ) : null}

        {!platformMode && workspaceTab === "emergency" && (canTaView || canEditPayrollRecords) && (hasPayroll || canTaAdd) ? (
          <Paper variant="outlined" sx={{ p: 2 }}>
            <ProfileSection n={4} title={t("profile.sectionEmergency")} hint={t("profile.sectionEmergencyHint")}>
            <Stack spacing={1.5}>
              {emergency.map((row, i) => (
                <Stack key={i} spacing={1}>
                  <Typography variant="caption" color="text.secondary">
                    {t("profile.emergencyN").replace("{n}", String(i + 1))}
                  </Typography>
                  <TextField
                    label={t("hr.ecName")}
                    value={row.name}
                    onChange={(e) =>
                      setEmergency((rows) => rows.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))
                    }
                    size="small"
                    fullWidth
                    disabled={!canEditHrExtras}
                  />
                  <TextField
                    label={t("hr.ecRelation")}
                    value={row.relationship}
                    onChange={(e) =>
                      setEmergency((rows) => rows.map((r, j) => (j === i ? { ...r, relationship: e.target.value } : r)))
                    }
                    size="small"
                    fullWidth
                    disabled={!canEditHrExtras}
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                    <TextField
                      label={t("hr.ecPhone")}
                      value={row.phone}
                      onChange={(e) =>
                        setEmergency((rows) =>
                          rows.map((r, j) =>
                            j === i ? { ...r, phone: normalizeUsPhoneDigits(e.target.value) } : r,
                          ),
                        )
                      }
                      size="small"
                      fullWidth
                      disabled={!canEditHrExtras}
                      inputProps={{ inputMode: "numeric", maxLength: 10 }}
                    />
                    <TextField
                      label={t("hr.ecAltPhone")}
                      value={row.alt_phone}
                      onChange={(e) =>
                        setEmergency((rows) =>
                          rows.map((r, j) =>
                            j === i ? { ...r, alt_phone: normalizeUsPhoneDigits(e.target.value) } : r,
                          ),
                        )
                      }
                      size="small"
                      fullWidth
                      disabled={!canEditHrExtras}
                    />
                  </Stack>
                  {canEditHrExtras && emergency.length > 1 ? (
                    <Button size="small" color="error" onClick={() => setEmergency((rows) => rows.filter((_, j) => j !== i))}>
                      {t("profile.removeEmergency")}
                    </Button>
                  ) : null}
                </Stack>
              ))}
              {canEditHrExtras ? (
                <Button
                  size="small"
                  startIcon={<Add />}
                  onClick={() => setEmergency((rows) => [...rows, emptyEmergencyRow()])}
                  disabled={emergency.length >= 6}
                >
                  {t("profile.addEmergency")}
                </Button>
              ) : null}
            </Stack>
            </ProfileSection>
          </Paper>
        ) : null}

        {!platformMode && workspaceTab === "notes" && (canTaView || canEditPayrollRecords) && (hasPayroll || canTaAdd) ? (
          <Paper variant="outlined" sx={{ p: 2 }}>
            <ProfileSection n={5} title={t("profile.sectionHrNotes")} hint={t("profile.sectionHrNotesHint")}>
            <TextField
              value={profileHrNotes}
              onChange={(e) => setProfileHrNotes(e.target.value)}
              fullWidth
              multiline
              minRows={2}
              size="small"
              disabled={!canEditHrExtras}
              placeholder={t("profile.hrNotesPlaceholder")}
            />
            </ProfileSection>
          </Paper>
        ) : null}

        {!platformMode && workspaceTab === "documents" && hasPayroll && (canTaView || canEditPayrollRecords) ? (
          <Paper variant="outlined" sx={{ p: 2 }}>
            <ProfileSection n={6} title={t("profile.sectionFormPackets")} hint={t("profile.documentsTabCenterHint")}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                {t("profile.documentsTabIntro")}
              </Typography>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1 }} useFlexGap flexWrap="wrap">
                <Button variant="contained" size="small" onClick={() => navigate("/documents")}>
                  {t("profile.openOrgDocumentsCenter")}
                </Button>
                <Button variant="outlined" size="small" onClick={() => navigate(`/employees/${uid}/hr`)}>
                  {t("profile.openEmployeeFormsWorkspace")}
                </Button>
              </Stack>
              <Alert severity="info" variant="outlined" sx={{ mt: 1 }}>
                {t("profile.documentsTabComplianceReminder")}
              </Alert>
            </ProfileSection>
          </Paper>
        ) : null}

        <Box
          sx={{
            position: "sticky",
            bottom: 0,
            zIndex: 3,
            bgcolor: "background.paper",
            borderTop: "1px solid",
            borderColor: "divider",
            pt: 1.5,
            mt: 2,
            pb: "env(safe-area-inset-bottom, 0px)",
          }}
        >
          <Stack direction="row" spacing={1} justifyContent="flex-end">
            <Button variant="outlined" onClick={() => navigate(platformMode ? "/platform" : "/employees")}>
              {t("common.cancel")}
            </Button>
            <Button variant="contained" onClick={save} disabled={saving}>
              {saving ? t("common.saving") : t("common.save")}
            </Button>
          </Stack>
        </Box>
      </Stack>
    </Box>
  );
}
