import { Button, Stack } from "@mui/material";
import { alpha } from "@mui/material/styles";
import { useI18n } from "../i18n/I18nContext";
import { OPS_MOBILE } from "./tokens";

/** Compact EN | ES toggle for shared-device Mobile Ops / PIN surfaces. */
export default function OpsLocaleToggle({ sx = {} } = {}) {
  const { locale, setLocale, t } = useI18n();
  return (
    <Stack
      direction="row"
      spacing={0.5}
      sx={{
        flexShrink: 0,
        p: 0.35,
        borderRadius: `${OPS_MOBILE.radius.button}px`,
        bgcolor: alpha(OPS_MOBILE.navy, 0.06),
        ...sx,
      }}
      role="group"
      aria-label={t("mobileOps.lang.label")}
    >
      {[
        { id: "en", label: t("mobileOps.lang.en") },
        { id: "es", label: t("mobileOps.lang.es") },
      ].map((opt) => {
        const active = locale === opt.id;
        return (
          <Button
            key={opt.id}
            size="small"
            onClick={() => setLocale(opt.id)}
            aria-pressed={active}
            sx={{
              minWidth: 40,
              minHeight: 36,
              px: 1,
              py: 0.25,
              borderRadius: `${OPS_MOBILE.radius.button - 2}px`,
              textTransform: "none",
              fontWeight: 900,
              fontSize: "0.82rem",
              letterSpacing: "0.04em",
              color: active ? "#fff" : OPS_MOBILE.navy,
              bgcolor: active ? OPS_MOBILE.blue : "transparent",
              "&:hover": {
                bgcolor: active ? OPS_MOBILE.blue : alpha(OPS_MOBILE.navy, 0.08),
              },
            }}
          >
            {opt.label}
          </Button>
        );
      })}
    </Stack>
  );
}
