import { useEffect, useState, type CSSProperties } from "react";

import { ITEM_PHOTO_BACKUP_DELAY_MS, NOT_FOUND_IMAGE_URL } from "../constants";

import "./ItemPhoto.css";

const BACKUP: CSSProperties = { "--iq-item-photo-backup": `url("${NOT_FOUND_IMAGE_URL}")` } as CSSProperties;

type ItemPhotoProps = {
  src: string;
  name: string;
};

/** An item's picture in its own box: empty, then the photo, or the backup once the photo is late. */
export function ItemPhoto({ src, name }: ItemPhotoProps) {
  const [shown, setShown] = useState(false);
  const [late, setLate] = useState(false);

  useEffect(() => {
    if (shown) return;
    const timer = window.setTimeout(() => setLate(true), ITEM_PHOTO_BACKUP_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [shown]);

  return (
    <span className={late ? "iq-item-photo iq-item-photo-late" : "iq-item-photo"} style={BACKUP}>
      <img
        ref={(image) => {
          if (image?.complete && image.naturalWidth > 0) setShown(true);
        }}
        className={shown ? "iq-item-photo-shown" : undefined}
        src={src}
        alt={name}
        loading="eager"
        fetchPriority="high"
        decoding="async"
        onLoad={() => setShown(true)}
      />
    </span>
  );
}
