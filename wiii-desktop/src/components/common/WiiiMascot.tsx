import type { ImgHTMLAttributes } from "react";

interface WiiiMascotProps
  extends Omit<ImgHTMLAttributes<HTMLImageElement>, "width" | "height" | "src"> {
  size?: number;
}

/** Neko Peek mascot used on generous brand surfaces. */
export function WiiiMascot({ size = 96, alt = "", ...props }: WiiiMascotProps) {
  return (
    <img
      src="/wiii-mascot-full.png"
      width={size}
      height={size}
      alt={alt}
      aria-hidden={alt ? undefined : true}
      draggable={false}
      {...props}
    />
  );
}
