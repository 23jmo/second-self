"use client";

import { useEffect, useState } from "react";
import MascotFace from "@/components/mascot/MascotFace";

const STEPS = [
  "searching web presence",
  "analyzing communication style",
  "mapping tools & workflows",
  "building voice profile",
  "initializing second session",
];

interface BuildingScreenProps {
  onComplete: () => void;
}

export default function BuildingScreen({ onComplete }: BuildingScreenProps) {
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setActiveStep((prev) => {
        if (prev >= STEPS.length - 1) {
          clearInterval(interval);
          return prev;
        }
        return prev + 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (activeStep >= STEPS.length - 1) {
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
      </div>
    </div>
  );
}
