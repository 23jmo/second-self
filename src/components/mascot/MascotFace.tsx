"use client";

import { useEffect } from "react";
import { motion, useTransform, useSpring, MotionValue } from "motion/react";

interface MascotFaceProps {
  className?: string;
  /** Override look direction (-1 to 1). When undefined, follows mouse. */
  lookX?: number;
  lookY?: number;
}

function useMousePosition() {
  const x = useSpring(0, { stiffness: 120, damping: 14 });
  const y = useSpring(0, { stiffness: 120, damping: 14 });

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      x.set((e.clientX / window.innerWidth) * 2 - 1);
      y.set((e.clientY / window.innerHeight) * 2 - 1);
    };
    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, [x, y]);

  return { x, y };
}

export default function MascotFace({ className = "w-48 md:w-52", lookX, lookY }: MascotFaceProps) {
  const mouse = useMousePosition();
  const hasOverride = lookX !== undefined || lookY !== undefined;

  // Single pair of output springs — always smooth, never jumps
  const outX = useSpring(0, { stiffness: 80, damping: 14 });
  const outY = useSpring(0, { stiffness: 80, damping: 14 });

  // Drive outputs from either override or mouse
  useEffect(() => {
    if (hasOverride) {
      outX.set(lookX ?? 0);
      outY.set(lookY ?? 0);
    }
  }, [hasOverride, lookX, lookY, outX, outY]);

  useEffect(() => {
    if (hasOverride) return;
    // Subscribe to mouse spring and forward values
    const unsubX = mouse.x.on("change", (v: number) => outX.set(v));
    const unsubY = mouse.y.on("change", (v: number) => outY.set(v));
    return () => { unsubX(); unsubY(); };
  }, [hasOverride, mouse.x, mouse.y, outX, outY]);

  const headX = useTransform(outX, [-1, 1], [-8, 8]);
  const headY = useTransform(outY, [-1, 1], [-6, 6]);
  const headRotate = useTransform(outX, [-1, 1], [-8, 8]);

  const eyeX = useTransform(outX, [-1, 1], [-12, 12]);
  const eyeY = useTransform(outY, [-1, 1], [-10, 10]);

  return (
    <div className={className}>
      <svg
        viewBox="0 0 212 212"
        overflow="visible"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-auto"
      >
        <defs>
          <filter id="face-shadow" x="0" y="0" width="212" height="212" filterUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
            <feFlood floodOpacity="0" result="BackgroundImageFix" />
            <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha" />
            <feOffset dy="4" />
            <feGaussianBlur stdDeviation="2" />
            <feComposite in2="hardAlpha" operator="out" />
            <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.25 0" />
            <feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow" />
            <feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow" result="shape" />
          </filter>
          <linearGradient id="face-gradient" x1="106" y1="0" x2="106" y2="204" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FBFFD4" />
            <stop offset="1" stopColor="#9CA161" />
          </linearGradient>
        </defs>

        <motion.g
          style={{ x: headX, y: headY, rotate: headRotate }}
          className="origin-center"
        >
          {/* Head circle */}
          <g filter="url(#face-shadow)">
            <circle cx="106" cy="102" r="102" fill="url(#face-gradient)" />
          </g>

          {/* Eyes */}
          <motion.g style={{ x: eyeX, y: eyeY }}>
            <ellipse cx="72" cy="94.5" rx="13" ry="12.5" fill="#9CA161" />
            <ellipse cx="140" cy="94.5" rx="13" ry="12.5" fill="#9CA161" />
          </motion.g>

          {/* Nose */}
          <path
            d="M96.0911 123.69L103.777 107.851C104.894 105.548 108.197 105.612 109.224 107.957L116.159 123.797C117.027 125.779 115.575 128 113.411 128H98.7901C96.5755 128 95.1243 125.683 96.0911 123.69Z"
            fill="#9CA161"
            stroke="#9CA161"
            strokeWidth="2"
          />

          {/* Mouth */}
          <path
            d="M93 137C93 137 99.5783 140 105.843 140C112.108 140 119 137 119 137"
            stroke="#9CA161"
            strokeWidth="3"
            fill="none"
          />
        </motion.g>
      </svg>
    </div>
  );
}
