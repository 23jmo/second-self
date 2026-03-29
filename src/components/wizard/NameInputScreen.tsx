"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import MascotFace from "@/components/mascot/MascotFace";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import ArrowIcon from "@/components/ui/ArrowIcon";

interface NameInputScreenProps {
  onSubmit: (name: string, role: string) => void;
  onBack?: () => void;
}

type FocusedField = "name" | "role" | null;

export default function NameInputScreen({ onSubmit, onBack }: NameInputScreenProps) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [focused, setFocused] = useState<FocusedField>(null);

  const isValid = name.trim().length > 0 && role.trim().length > 0;
  const nameTagVisible = name.trim().length > 0;

  const handleSubmit = () => {
    if (!isValid) return;
    onSubmit(name.trim(), role.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSubmit();
  };

  // --- Eye direction state machine ---
  let lookX: number | undefined;
  let lookY: number | undefined;

  if (focused === "name") {
    const progress = Math.min(name.length / 20, 1);
    lookX = -0.6 + progress * 1.2;
    lookY = 0.5;
  } else if (focused === "role") {
    const progress = Math.min(role.length / 25, 1);
    lookX = -0.6 + progress * 1.2;
    lookY = 0.8;
  } else if (nameTagVisible) {
    lookX = 0;
    lookY = -1;
  }

  return (
    <div className="relative flex flex-col items-center w-full max-w-[615px] px-4" onKeyDown={handleKeyDown}>
      {onBack && (
        <button
          onClick={onBack}
          className="absolute top-0 left-4 flex items-center gap-1 text-sm text-black/40 hover:text-black/60 transition-colors"
        >
          <ArrowIcon className="w-4 h-4 rotate-180" />
          back
        </button>
      )}
      {/* Name tag above mascot */}
      <div className="h-10 sm:h-12 flex items-end justify-center">
        <AnimatePresence>
          {nameTagVisible && (
            <motion.div
              initial={{ opacity: 0, y: 8, scale: 0.85 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.85 }}
              transition={{ type: "spring", stiffness: 200, damping: 18 }}
            >
              <div className="bg-[#FBFFD4] border border-[rgba(156,161,97,0.8)] rounded-[15px] px-6 sm:px-9 py-2 sm:py-3 shadow-[0px_4px_4px_rgba(0,0,0,0.25)] whitespace-nowrap">
                <p className="text-sm sm:text-base lg:text-lg font-normal text-primary-dark text-center">
                  {name.trim()}
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Peeking mascot */}
      <div
        className="w-28 sm:w-36 md:w-44 mb-[-30px] sm:mb-[-40px] z-10"
        style={{
          maskImage: "linear-gradient(to bottom, black 30%, black 55%, transparent 90%)",
          WebkitMaskImage: "linear-gradient(to bottom, black 30%, black 55%, transparent 90%)",
        }}
      >
        <MascotFace className="w-full" lookX={lookX} lookY={lookY} />
      </div>

      {/* Content */}
      <div className="flex flex-col items-center gap-8 w-full">
        <div className="flex flex-col items-center gap-6 w-full">
          <div className="flex flex-col items-center w-full">
            <h1 className="text-3xl sm:text-4xl lg:text-[56px] lg:leading-[64px] font-normal text-black text-center">
              what do we call{" "}
              <span className="font-semibold text-primary">you?</span>
            </h1>
            <p className="text-base sm:text-lg lg:text-2xl font-normal text-black text-center mt-1">
              your second self needs to know who it&apos;s representing.
            </p>
          </div>

          <div className="flex flex-col gap-5 w-full max-w-[595px]">
            <Input
              placeholder="your first name"
              value={name}
              onChange={setName}
              onFocus={() => setFocused("name")}
              onBlur={() => setFocused(null)}
            />
            <Input
              placeholder="what do you do? (e.g. designer, founder, etc.)"
              value={role}
              onChange={setRole}
              onFocus={() => setFocused("role")}
              onBlur={() => setFocused(null)}
            />
          </div>
        </div>

        <Button onClick={handleSubmit} disabled={!isValid}>
          that&apos;s me
        </Button>
      </div>
    </div>
  );
}
