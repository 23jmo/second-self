"use client";

import { useEffect, useRef, useState } from "react";
import MascotFace from "@/components/mascot/MascotFace";
import { postOnboard } from "@/lib/api";
import type { SecondSelfProfile } from "@/lib/api";

const STEPS = [
  "searching web presence",
  "analyzing communication style",
  "mapping tools & workflows",
  "building voice profile",
  "initializing second self",
];

interface BuildingScreenProps {
  name: string;
  role: string;
  email: string;
  sessionId: string;
  onComplete: () => void;
  onProfile: (profile: SecondSelfProfile) => void;
}

export default function BuildingScreen({
  name,
  role,
  email,
  sessionId,
  onComplete,
  onProfile,
}: BuildingScreenProps) {
  const [activeStep, setActiveStep] = useState(0);
  const [error, setError] = useState("");
  const apiDone = useRef(false);
  const profileRef = useRef<SecondSelfProfile | null>(null);

  // Animate steps on a timer (one per second)
  useEffect(() => {
    const interval = setInterval(() => {
      setActiveStep((prev) => {
        // Don't go past the second-to-last step until API is done
        const limit = apiDone.current ? STEPS.length - 1 : STEPS.length - 2;
        if (prev >= limit) {
          if (prev >= STEPS.length - 1) clearInterval(interval);
          return prev;
        }
        return prev + 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  // Call /onboard on mount (once only)
  const onProfileRef = useRef(onProfile);
  onProfileRef.current = onProfile;
  const hasFired = useRef(false);

  useEffect(() => {
    if (hasFired.current) return;
    hasFired.current = true;
    let cancelled = false;

    async function run() {
      try {
        const resp = await postOnboard(name, email, role, sessionId);
        if (cancelled) return;
        apiDone.current = true;
        profileRef.current = resp.profile;
        onProfileRef.current(resp.profile);
        // Jump to final step
        setActiveStep(STEPS.length - 1);
      } catch (err) {
        if (cancelled) return;
        console.error("Onboard failed:", err);
        setError(err instanceof Error ? err.message : "Something went wrong.");
      }
    }

    run();
    return () => { cancelled = true; };
  }, [name, email, role, sessionId]);

  // Advance to next screen once we hit the last step
  useEffect(() => {
    if (activeStep >= STEPS.length - 1 && apiDone.current) {
      const timeout = setTimeout(onComplete, 1200);
      return () => clearTimeout(timeout);
    }
  }, [activeStep, onComplete]);

  return (
    <div className="flex flex-col items-center gap-6 w-full max-w-[473px] px-4">
      <MascotFace className="w-36 sm:w-44 md:w-52" />

      <div className="flex flex-col items-center gap-7 w-full text-center">
        <div className="flex flex-col items-center w-full">
          <h1 className="text-3xl sm:text-4xl lg:text-[56px] lg:leading-[64px] font-normal text-black">
            building your{" "}
            <span className="font-semibold text-primary">twin</span>
          </h1>
          <p className="text-base sm:text-lg lg:text-2xl font-normal text-black mt-1">
            scanning your digital footprint to build an accurate second self.
          </p>
        </div>

        <ul className="flex flex-col items-center gap-1 text-base sm:text-lg lg:text-2xl">
          {STEPS.map((step, i) => (
            <li
              key={step}
              className={`flex items-center gap-2 transition-all duration-300 ${
                i === activeStep
                  ? "font-semibold text-primary"
                  : i < activeStep
                  ? "text-black"
                  : "text-black/40"
              }`}
            >
              <span className="text-sm">&#8226;</span>
              {step}
            </li>
          ))}
        </ul>

        {error && (
          <p className="text-red-500 text-sm text-center">{error}</p>
        )}

        <button
          onClick={() => {
            apiDone.current = true;
            onComplete();
          }}
          className="text-sm text-black/40 hover:text-black/70 transition-colors underline underline-offset-2"
        >
          skip
        </button>
      </div>
    </div>
  );
}
