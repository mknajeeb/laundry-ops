/** Company entities that can issue contractor invoices / payment receipts. */

import { VEEWASH_LOGO_URL } from "../theme/veewashBrand";
import {
  VEEWASH_DEFAULT_ADDRESS,
  VEEWASH_PHONE,
  VEEWASH_WEBSITE,
  VEEWASH_WEBSITE_LABEL,
} from "./companyContact";

export const WASHMATE_LOGO_URL = "/assets/washmate-logo.png";

export const ISSUER_ENTITIES = [
  { key: "veewash", label: "VeeWash" },
  { key: "washmate", label: "Washmate" },
];

export const ISSUER_PROFILES = {
  veewash: {
    issued_by_entity: "veewash",
    company_name: "VeeWash",
    company_address: VEEWASH_DEFAULT_ADDRESS,
    company_phone: VEEWASH_PHONE,
    company_website: VEEWASH_WEBSITE,
    company_website_label: VEEWASH_WEBSITE_LABEL,
    organization_logo_url: VEEWASH_LOGO_URL,
  },
  washmate: {
    issued_by_entity: "washmate",
    company_name: "Washmate Laundry Solutions",
    company_address: "921 2nd Avenue, Franklin Square, NY 11010",
    company_phone: VEEWASH_PHONE,
    company_website: "",
    company_website_label: "",
    organization_logo_url: WASHMATE_LOGO_URL,
  },
};

export function resolveIssuerEntity(entity) {
  const key = String(entity || "veewash").toLowerCase();
  return ISSUER_PROFILES[key] ? key : "veewash";
}

/** Merge issuer branding into print prefill (logo, name, address). */
export function buildIssuerPrintPrefill(prefill, record) {
  const entity = resolveIssuerEntity(record?.issued_by_entity || prefill?.issued_by_entity);
  const profile = ISSUER_PROFILES[entity];
  return {
    ...(prefill || {}),
    ...profile,
    issued_by_entity: entity,
    issue_from_name: record?.issue_from_name || "",
    issue_from_address: record?.issue_from_address || "",
  };
}
