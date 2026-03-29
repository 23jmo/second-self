interface MascotFullBodyLookUpProps {
  className?: string;
}

/** Exact Figma export of Pose #1 from node 53:143 — eyes positioned looking up */
export default function MascotFullBodyLookUp({ className = "w-48 md:w-52" }: MascotFullBodyLookUpProps) {
  return (
    <div className={className}>
      <svg
        viewBox="0 0 197.059 258"
        overflow="visible"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-auto"
      >
        <defs>
          <filter id="body-up-shadow" x="31.9302" y="0" width="131.584" height="131.584" filterUnits="userSpaceOnUse" colorInterpolationFilters="sRGB">
            <feFlood floodOpacity="0" result="BackgroundImageFix" />
            <feColorMatrix in="SourceAlpha" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0" result="hardAlpha" />
            <feOffset dy="4" />
            <feGaussianBlur stdDeviation="2" />
            <feComposite in2="hardAlpha" operator="out" />
            <feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.25 0" />
            <feBlend mode="normal" in2="BackgroundImageFix" result="effect1_dropShadow" />
            <feBlend mode="normal" in="SourceGraphic" in2="effect1_dropShadow" result="shape" />
          </filter>
          <linearGradient id="up-leg-r" x1="125.671" y1="204.58" x2="125.671" y2="258" gradientUnits="userSpaceOnUse">
            <stop stopColor="#9CA161" />
            <stop offset="1" stopColor="#FBFFD4" />
          </linearGradient>
          <linearGradient id="up-leg-l" x1="75.287" y1="204.58" x2="75.287" y2="258" gradientUnits="userSpaceOnUse">
            <stop stopColor="#9CA161" />
            <stop offset="1" stopColor="#FBFFD4" />
          </linearGradient>
          <linearGradient id="up-torso" x1="100.004" y1="114.078" x2="100.004" y2="213.732" gradientUnits="userSpaceOnUse">
            <stop stopColor="#9CA161" />
            <stop offset="1" stopColor="#FBFFD4" />
          </linearGradient>
          <linearGradient id="up-head" x1="97.7223" y1="0" x2="97.7223" y2="123.584" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FBFFD4" />
            <stop offset="1" stopColor="#9CA161" />
          </linearGradient>
          <linearGradient id="up-arm-l" x1="33.5536" y1="115.028" x2="33.5536" y2="152.484" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FBFFD4" />
            <stop offset="1" stopColor="#9CA161" />
          </linearGradient>
          <linearGradient id="up-arm-r" x1="165.073" y1="113.127" x2="165.073" y2="156.353" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FBFFD4" />
            <stop offset="1" stopColor="#9CA161" />
          </linearGradient>
        </defs>

        {/* Right leg */}
        <path d="M130.805 243.176L127.953 204.58L105.137 208.762L107.039 255.534C107.039 255.534 139.551 262.189 139.551 253.633C139.551 244.58 130.805 243.176 130.805 243.176Z" fill="url(#up-leg-r)" />
        {/* Left leg */}
        <path d="M70.1535 243.176L73.0055 204.58L95.821 208.762L93.9197 255.534C93.9197 255.534 61.4075 262.189 61.4075 253.633C61.4075 244.58 70.1535 243.176 70.1535 243.176Z" fill="url(#up-leg-l)" />
        {/* Torso */}
        <path d="M51.1406 176.631C51.1406 147.16 65.02 111.606 65.02 111.606H132.516C132.516 111.606 148.867 140.506 148.867 176.631C148.867 192.014 145.255 207.241 131.185 212.945C111.781 220.812 91.8283 218.839 73.1956 212.945C57.7626 208.063 51.1406 195.318 51.1406 176.631Z" fill="url(#up-torso)" />
        {/* Head */}
        <g filter="url(#body-up-shadow)">
          <circle cx="97.7223" cy="61.7922" r="61.7922" fill="url(#up-head)" />
        </g>
        {/* Left arm */}
        <path d="M3.22787 129.668C11.0389 122.626 63.8792 115.028 63.8792 115.028L59.3161 133.471L31.5572 143.548C31.5572 143.548 30.4277 152.891 26.4237 152.484C22.621 152.098 22.431 143.548 22.431 143.548L12.7344 146.59C3.03773 149.632 -4.58312 136.711 3.22787 129.668Z" fill="url(#up-arm-l)" />
        {/* Right arm */}
        <path d="M193.738 134.612C187.083 127.767 133.086 113.127 133.086 113.127L142.593 136.513L168.451 145.069C168.451 145.069 166.978 154.085 170.922 155.716C172.775 156.482 174.279 156.644 176.056 155.716C178.699 154.335 178.527 148.491 178.527 148.491C178.527 148.491 185.097 153.13 189.365 151.914C196.067 150.003 200.392 141.456 193.738 134.612Z" fill="url(#up-arm-r)" />
        {/* Eyes */}
        <circle cx="78.8246" cy="24.7953" r="7.79532" fill="#9CA161" />
        <circle cx="115.825" cy="24.7953" r="7.79532" fill="#9CA161" />
        {/* Nose */}
        <path d="M91.7995 31.8141L97.0785 21.7713C97.462 21.0417 98.5139 21.0633 98.8671 21.808L103.631 31.8508C103.946 32.5143 103.462 33.2794 102.728 33.2794H92.6847C91.9324 33.2794 91.4495 32.48 91.7995 31.8141Z" fill="#9CA161" stroke="#9CA161" />
        {/* Mouth */}
        <path d="M90.0293 41C90.0293 41 94.022 42.3309 97.8246 42.3309C101.627 42.3309 105.81 41 105.81 41" stroke="#9CA161" strokeWidth="3" fill="none" />
      </svg>
    </div>
  );
}
