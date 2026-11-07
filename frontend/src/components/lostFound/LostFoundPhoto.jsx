import { useEffect, useState } from "react";
import { getLostFoundPhoto, getPinLostFoundPhoto } from "../../api";

export default function LostFoundPhoto({ photoId, hub, alt = "" }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    const load = async () => {
      const res = hub
        ? await getPinLostFoundPhoto(hub.organization_slug, hub.token, photoId)
        : await getLostFoundPhoto(photoId);
      if (cancelled || res?.status >= 400 || !(res?.data instanceof Blob)) return;
      objectUrl = URL.createObjectURL(res.data);
      setUrl(objectUrl);
    };
    if (photoId) load().catch(() => {});
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [photoId, hub]);
  if (!url) return null;
  return (
    <img
      alt={alt}
      src={url}
      style={{ width: 96, height: 96, objectFit: "cover", borderRadius: 8 }}
    />
  );
}
