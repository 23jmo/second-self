"use client";

import { useEffect } from "react";
import { motion, useSpring, useTransform } from "motion/react";

interface MascotFullBodyProps {
  className?: string;
}

export default function MascotFullBody({ className = "w-48 md:w-52" }: MascotFullBodyProps) {
  const mouseX = useSpring(0, { stiffness: 120, damping: 14 });
  const mouseY = useSpring(0, { stiffness: 120, damping: 14 });

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      mouseX.set((e.clientX / window.innerWidth) * 2 - 1);
      mouseY.set((e.clientY / window.innerHeight) * 2 - 1);
    };
    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, [mouseX, mouseY]);

  const eyeX = useTransform(mouseX, [-1, 1], [-12, 12]);
  const eyeY = useTransform(mouseY, [-1, 1], [-10, 10]);

  return (
    <div className={className}>
      <svg
        viewBox="0 0 518.222 678.484"
        overflow="visible"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-auto"
      >
        <defs>
          <filter id="body-shadow" x="90.4886" y="0" width="333" height="333" filterUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
            <feFlood floodOpacity="0" result="BackgroundImageFix" />
            <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha" />
            <feOffset dy="4" />
            <feGaussianBlur stdDeviation="2" />
            <feComposite in2="hardAlpha" operator="out" />
            <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.25 0" />
            <feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow" />
            <feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow" result="shape" />
          </filter>
          <linearGradient id="body-leg-r" x1="330.489" y1="538" x2="330.489" y2="678.484" gradientUnits="userSpaceOnUse">
            <stop stopColor="#9CA161" />
            <stop offset="1" stopColor="#FBFFD4" />
          </linearGradient>
          <linearGradient id="body-leg-l" x1="197.989" y1="538" x2="197.989" y2="678.484" gradientUnits="userSpaceOnUse">
            <stop stopColor="#9CA161" />
            <stop offset="1" stopColor="#FBFFD4" />
          </linearGradient>
          <linearGradient id="body-torso" x1="262.989" y1="300" x2="262.989" y2="562.07" gradientUnits="userSpaceOnUse">
            <stop stopColor="#9CA161" />
            <stop offset="1" stopColor="#FBFFD4" />
          </linearGradient>
          <linearGradient id="body-head" x1="256.989" y1="0" x2="256.989" y2="325" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FBFFD4" />
            <stop offset="1" stopColor="#9CA161" />
          </linearGradient>
          <linearGradient id="body-arm-l" x1="88.2387" y1="302.5" x2="88.2387" y2="401" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FBFFD4" />
            <stop offset="1" stopColor="#9CA161" />
          </linearGradient>
          <linearGradient id="body-arm-r" x1="434.105" y1="297.5" x2="434.105" y2="411.175" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FBFFD4" />
            <stop offset="1" stopColor="#9CA161" />
          </linearGradient>
        </defs>

        {/* Right leg */}
        <path d="M343.989 639.5L336.489 538L276.489 549L281.489 672C281.489 672 366.989 689.5 366.989 667C366.989 643.192 343.989 639.5 343.989 639.5Z" fill="url(#body-leg-r)" />
        {/* Left leg */}
        <path d="M184.489 639.5L191.989 538L251.989 549L246.989 672C246.989 672 161.489 689.5 161.489 667C161.489 643.192 184.489 639.5 184.489 639.5Z" fill="url(#body-leg-l)" />
        {/* Torso */}
        <path d="M134.489 464.5C134.489 387 170.989 293.5 170.989 293.5H348.489C348.489 293.5 391.489 369.5 391.489 464.5C391.489 504.955 381.989 545 344.989 560C293.959 580.688 241.489 575.5 192.489 560C151.903 547.162 134.489 513.643 134.489 464.5Z" fill="url(#body-torso)" />
        {/* Head */}
        <g filter="url(#body-shadow)">
          <circle cx="256.989" cy="162.5" r="162.5" fill="url(#body-head)" />
        </g>
        {/* Eyes — follow cursor */}
        <motion.g style={{ x: eyeX, y: eyeY }}>
          <circle cx="202.989" cy="150.5" r="20.5" fill="#9CA161" />
          <circle cx="310.989" cy="150.5" r="20.5" fill="#9CA161" />
        </motion.g>
        {/* Nose */}
        <path d="M239.659 199.658L255.166 168.645C256.297 166.384 259.545 166.448 260.584 168.752L274.578 199.766C275.474 201.752 274.022 204 271.844 204H242.343C240.113 204 238.662 201.653 239.659 199.658Z" fill="#9CA161" stroke="#9CA161" strokeWidth="2" />
        {/* Left arm */}
        <path d="M8.48859 341C29.0298 322.48 167.989 302.5 167.989 302.5L155.989 351L82.9886 377.5C82.9886 377.5 80.0183 402.07 69.4886 401C59.4883 399.984 58.9886 377.5 58.9886 377.5L33.4886 385.5C7.98856 393.5 -12.0526 359.52 8.48859 341Z" fill="url(#body-arm-l)" />
        {/* Right arm */}
        <path d="M509.489 354C491.989 336 349.989 297.5 349.989 297.5L374.989 359L442.989 381.5C442.989 381.5 439.115 405.21 449.489 409.5C454.36 411.515 458.316 411.941 462.989 409.5C469.939 405.869 469.489 390.5 469.489 390.5C469.489 390.5 486.764 402.699 497.989 399.5C515.614 394.476 526.989 372 509.489 354Z" fill="url(#body-arm-r)" />
        {/* Mouth */}
        <path d="M236.489 219C236.489 219 246.989 222.5 256.989 222.5C266.989 222.5 277.989 219 277.989 219" stroke="#9CA161" strokeWidth="3" fill="none" />
      </svg>
    </div>
  );
}
