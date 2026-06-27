import { useEffect, useState } from "react";
import { contractorLogoSrc, EMBEDDED_VEEWASH_LOGO } from "./contractorLogo";

/** Logo for print: issuer profile logo when set, else org logo, else VeeWash fallback. */
export default function ContractorPrintLogo({ prefill, className }) {
  const preferred = contractorLogoSrc(prefill);
  const [src, setSrc] = useState(preferred);

  useEffect(() => {
    setSrc(contractorLogoSrc(prefill));
  }, [prefill?.issued_by_entity, prefill?.organization_logo_url]);

  return (
    <img
      src={src}
      alt=""
      className={className}
      onError={() => {
        if (src !== EMBEDDED_VEEWASH_LOGO) setSrc(EMBEDDED_VEEWASH_LOGO);
      }}
    />
  );
}
