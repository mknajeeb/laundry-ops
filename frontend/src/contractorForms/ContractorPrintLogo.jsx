import { useEffect, useState } from "react";
import { contractorLogoSrc, EMBEDDED_VEEWASH_LOGO } from "./contractorLogo";

/** Logo for print: org logo when valid, else bundled VeeWash asset. */
export default function ContractorPrintLogo({ prefill, className }) {
  const preferred = contractorLogoSrc(prefill);
  const [src, setSrc] = useState(preferred);

  useEffect(() => {
    setSrc(contractorLogoSrc(prefill));
  }, [prefill?.organization_logo_url]);

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
