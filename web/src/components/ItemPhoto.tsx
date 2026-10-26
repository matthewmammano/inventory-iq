import { useState } from "react";

import { NOT_FOUND_IMAGE_URL } from "../constants";

import "./ItemPhoto.css";

type ItemPhotoProps = {
  src: string;
  name: string;
};

/** An item's picture in its own fixed box, falling back to the placeholder when the file will not load. */
export function ItemPhoto({ src, name }: ItemPhotoProps) {
  const [failed, setFailed] = useState(false);

  return (
    <span className="iq-item-photo">
      <img
        src={failed ? NOT_FOUND_IMAGE_URL : src}
        alt={name}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
      />
    </span>
  );
}
