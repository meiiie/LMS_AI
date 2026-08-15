import { motion, type Transition } from "motion/react";
import type { NekoResolvedPose } from "./neko-motion-model";

interface NekoRigProps {
  pose: NekoResolvedPose;
  blinkToken: number;
  reducedMotion: boolean;
  stiffness: number;
  damping: number;
  materialMode: boolean;
}
function spring(stiffness: number, damping: number, reducedMotion: boolean): Transition {
  if (reducedMotion) return { duration: 0 };
  return { type: "spring", stiffness, damping, mass: 0.9 };
}

export function NekoRig({
  pose,
  blinkToken,
  reducedMotion,
  stiffness,
  damping,
  materialMode,
}: NekoRigProps) {
  const transition = spring(stiffness, damping, reducedMotion);
  const eyeX = pose.gazeX * 4.5;
  const eyeY = pose.gazeY * 3.5;
  const eyeScaleY = Math.max(0.12, pose.eyeOpen);

  return (
    <motion.div
      className="neko-rig"
      animate={{
        y: pose.lift,
        rotate: pose.tilt,
        scale: pose.scale,
      }}
      transition={transition}
      data-testid="neko-rig"
      data-render-mode={materialMode ? "material" : "parametric"}
    >
      {materialMode ? (
        <motion.img
          className="neko-rig__material"
          src="/wiii-mascot-full.png"
          alt=""
          aria-hidden="true"
          draggable={false}
          animate={{ rotate: pose.tail * 0.6 }}
          transition={transition}
        />
      ) : (
        <svg
          className="neko-rig__vector"
          viewBox="0 0 256 256"
          aria-hidden="true"
          focusable="false"
        >
          <defs>
            <filter id="neko-lab-shadow" x="-30%" y="-30%" width="160%" height="180%">
              <feDropShadow dx="0" dy="10" stdDeviation="8" floodColor="#171615" floodOpacity="0.14" />
            </filter>
            <linearGradient id="neko-lab-body" x1="0" y1="0" x2="0.72" y2="1">
              <stop offset="0" stopColor="#fffdf7" />
              <stop offset="1" stopColor="#efe8dc" />
            </linearGradient>
            <linearGradient id="neko-lab-tail" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#373533" />
              <stop offset="1" stopColor="#252423" />
            </linearGradient>
          </defs>

          <ellipse cx="130" cy="226" rx="86" ry="12" fill="#272523" opacity="0.1" />
          <g filter="url(#neko-lab-shadow)">
            <motion.path
              fill="url(#neko-lab-tail)"
              d="M28 148C20 104 43 70 82 57c38-13 91-10 125 16 28 22 37 60 25 94-14 42-53 62-105 61-54-1-91-30-99-80Z"
              animate={{ rotate: pose.tail * -0.7, scale: 1 + Math.abs(pose.tail) * 0.005 }}
              transition={transition}
              style={{ transformOrigin: "128px 166px" }}
            />
            <motion.g
              animate={{
                x: pose.gazeX * 1.3,
                y: pose.gazeY * 0.9,
                rotate: pose.tilt * 0.12,
              }}
              transition={transition}
              style={{ transformOrigin: "136px 108px" }}
            >
              <path
                fill="url(#neko-lab-body)"
                d="M61 133c-7-22-6-53 1-77 5-18 18-25 34-15 21-11 49-14 76-8 10-18 28-18 37 1 10 21 12 52 4 78-8 26-36 42-72 43-36 1-70-7-80-22Z"
              />
              <path
                d="M75 54c10-8 16-6 25-1M174 45c10-10 20-8 27 3"
                fill="none"
                stroke="#ffffff"
                strokeLinecap="round"
                strokeOpacity="0.54"
                strokeWidth="4"
              />
              <motion.ellipse
                key={`left-eye-${blinkToken}`}
                cx="111"
                cy="103"
                rx="10"
                ry="15"
                fill="#2A2928"
                animate={{
                  x: eyeX,
                  y: eyeY,
                  scaleY: [eyeScaleY, 0.12, eyeScaleY],
                }}
                transition={
                  reducedMotion
                    ? { duration: 0 }
                    : { x: transition, y: transition, scaleY: { duration: 0.24, times: [0, 0.48, 1] } }
                }
                style={{ transformOrigin: "111px 103px" }}
              />
              <motion.ellipse
                key={`right-eye-${blinkToken}`}
                cx="157"
                cy="100"
                rx="10"
                ry="15"
                fill="#2A2928"
                animate={{
                  x: eyeX,
                  y: eyeY,
                  scaleY: [eyeScaleY, 0.12, eyeScaleY],
                }}
                transition={
                  reducedMotion
                    ? { duration: 0 }
                    : { x: transition, y: transition, scaleY: { duration: 0.24, delay: 0.015, times: [0, 0.48, 1] } }
                }
                style={{ transformOrigin: "157px 100px" }}
              />
            </motion.g>
            <motion.path
              fill="#454241"
              d="M31 136c31 23 72 38 117 41 33 2 61-7 84-29 3 24-7 47-29 62-23 16-59 22-100 16-43-6-71-31-77-63-2-10 0-19 5-27Z"
              animate={{
                rotate: pose.tail * 1.25,
                x: pose.tail * 1.8,
                y: Math.abs(pose.tail) * -0.8,
              }}
              transition={transition}
              style={{ transformOrigin: "86px 186px" }}
            />
          </g>

          <motion.g
            initial={false}
            animate={{ opacity: pose.statusDot ? 1 : 0, scale: pose.statusDot ? 1 : 0.72 }}
            transition={reducedMotion ? { duration: 0 } : { duration: 0.18 }}
            style={{ transformOrigin: "222px 45px" }}
          >
            <circle cx="222" cy="45" r="9" fill="#BBDDF2" />
            <circle cx="222" cy="45" r="13" fill="none" stroke="#BBDDF2" strokeOpacity="0.32" />
          </motion.g>
        </svg>
      )}
    </motion.div>
  );
}
