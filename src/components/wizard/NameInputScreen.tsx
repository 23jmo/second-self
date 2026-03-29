"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { initializeApp } from "firebase/app";
import { getAuth, signInWithPopup, GoogleAuthProvider } from "firebase/auth";
import MascotFace from "@/components/mascot/MascotFace";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { getFirebaseConfig, postAuthCallback } from "@/lib/api";

interface NameInputScreenProps {
  onSubmit: (name: string, role: string) => void;
  onSession: (sessionId: string, email: string) => void;
}

type FocusedField = "name" | "role" | null;

export default function NameInputScreen({ onSubmit, onSession }: NameInputScreenProps) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [focused, setFocused] = useState<FocusedField>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const isValid = name.trim().length > 0 && role.trim().length > 0;
  const nameTagVisible = name.trim().length > 0;

  const handleSubmit = async () => {
    if (!isValid || loading) return;
    setLoading(true);
    setError("");

    try {
      // 1. Get Firebase config from backend
      const config = await getFirebaseConfig();
      const app = initializeApp(config);
      const auth = getAuth(app);

      // 2. Google sign-in popup with required scopes
      const provider = new GoogleAuthProvider();
      provider.addScope("https://www.googleapis.com/auth/gmail.readonly");
      provider.addScope("https://www.googleapis.com/auth/gmail.send");
      provider.addScope("https://www.googleapis.com/auth/calendar.readonly");
      provider.addScope("https://www.googleapis.com/auth/calendar.events");
      provider.addScope("https://www.googleapis.com/auth/documents");
      provider.addScope("https://www.googleapis.com/auth/presentations");
      provider.addScope("https://www.googleapis.com/auth/drive.file");

      const result = await signInWithPopup(auth, provider);

      // 3. Extract tokens
      const credential = GoogleAuthProvider.credentialFromResult(result);
      const googleAccessToken = credential?.accessToken ?? "";
      const idToken = await result.user.getIdToken();
      const email = result.user.email ?? "";

      // 4. Send to backend to create session
      const resp = await postAuthCallback(idToken, googleAccessToken, email, name.trim());
      onSession(resp.session_id, email);

      // 5. Advance wizard
      onSubmit(name.trim(), role.trim());
    } catch (err) {
      console.error("Auth failed:", err);
      setError(err instanceof Error ? err.message : "Sign-in failed. Try again.");
      setLoading(false);
    }
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
    <div className="flex flex-col items-center w-full max-w-[615px] px-4" onKeyDown={handleKeyDown}>
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

        {error && (
          <p className="text-red-500 text-sm text-center">{error}</p>
        )}

        <Button onClick={handleSubmit} disabled={!isValid || loading}>
          {loading ? "signing in..." : "that\u0027s me"}
        </Button>
      </div>
    </div>
  );
}
