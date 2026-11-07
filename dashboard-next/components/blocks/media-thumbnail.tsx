"use client";

/* eslint-disable @next/next/no-img-element -- lazysizes owns the deferred private image source; Next optimization must not cache it. */
import { useEffect, useRef, useState } from "react";

const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

/** Preview only supported raster images through the existing authenticated proxy. */
export function MediaThumbnail({ mediaId, mimeType, alt }: {
  mediaId: number;
  mimeType: string;
  alt: string;
}) {
  if (!Number.isSafeInteger(mediaId) || mediaId <= 0 || !IMAGE_TYPES.has(mimeType)) return null;
  // Replacing an item remounts its image: old load/error events cannot settle the new source.
  return <ThumbnailImage key={mediaId} src={`/api/admin/preview/product/${mediaId}`} alt={alt} />;
}

/** Reserve layout while lazysizes loads a visible image, with a terminal error state. */
function ThumbnailImage({ src, alt }: { src: string; alt: string }) {
  const ref = useRef<HTMLImageElement>(null);
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");
  useEffect(() => {
    const image = ref.current;
    let active = true;
    // Import after hydration; the library mutates marker classes and data-src in the DOM.
    void import("lazysizes").then(({ default: lazySizes }) => {
      if (!active || !image) return;
      if (lazySizes.noSupport) { image.src = src; return; }
      image.classList.add("lazyload");
      lazySizes.init();
      lazySizes.loader.checkElems(false);
    }).catch(() => {
      // A missing JS chunk still permits the browser's native lazy-loading fallback.
      if (active && image) image.src = src;
    });
    return () => { active = false; image?.classList.remove("lazyload"); };
  }, [src]);

  return (
    <div data-media-thumbnail="" data-state={status}
      className="relative size-24 shrink-0 overflow-hidden rounded-lg border bg-muted">
      {status === "loading" ? <span aria-hidden="true" className="absolute inset-0 animate-pulse bg-muted" /> : null}
      <img ref={ref} data-src={src} data-expand="-20" width={96} height={96}
        loading="lazy" decoding="async" alt={alt}
        onLoad={(event) => { if (event.currentTarget.naturalWidth > 0) setStatus("loaded"); }}
        onError={() => setStatus("error")}
        className={`absolute inset-0 size-full object-contain ${status === "loaded" ? "opacity-100" : "opacity-0"}`} />
      {status === "error" ? <span className="absolute inset-0 flex items-center justify-center p-2 text-center text-xs leading-6 text-muted-foreground">
        تصویر بارگذاری نشد
      </span> : null}
      <noscript><img src={src} alt={alt} width={96} height={96} loading="lazy"
        className="absolute inset-0 size-full object-contain" /></noscript>
    </div>
  );
}
