import type { ImgHTMLAttributes } from "react";

interface WiiiMarkProps
  extends Omit<ImgHTMLAttributes<HTMLImageElement>, "width" | "height" | "src"> {
  size?: number;
  title?: string;
}

/** Compact product identity. WiiiAvatar remains the animated conversation character. */
export function WiiiMark({
  size = 20,
  title,
  alt,
  ...props
}: WiiiMarkProps) {
  return (
    <img
      src="/icon-192.png"
      width={size}
      height={size}
      alt={alt ?? ""}
      title={title}
      aria-hidden={alt || title ? undefined : true}
      draggable={false}
      {...props}
    />
  );
}
