"use client";

import { useState } from "react";
import { initializeApp } from "firebase/app";
import { getAuth, signInWithPopup, GoogleAuthProvider } from "firebase/auth";
import MascotFullBody from "@/components/mascot/MascotFullBody";
import Button from "@/components/ui/Button";
import { getFirebaseConfig, postAuthCallback } from "@/lib/api";

interface WelcomeScreenProps {
  onNext: () => void;
  onSession: (sessionId: string, email: string) => void;
}

export default function WelcomeScreen({ onNext, onSession }: WelcomeScreenProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleClick = async () => {
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
      const name = result.user.displayName ?? "";

      // 4. Send to backend to create session
      const resp = await postAuthCallback(idToken, googleAccessToken, email, name);
      onSession(resp.session_id, email);

      // 5. Advance wizard
      onNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed. Try again.");
      setLoading(false);
    }
  };

  const handleSkipAuth = () => {
    const demoSessionId = `demo-${crypto.randomUUID()}`;
    onSession(demoSessionId, "");
    onNext();
  };

  return (
    <div className="flex flex-col items-center gap-3 w-full max-w-[615px] px-4">
      <MascotFullBody className="w-36 sm:w-44 md:w-52" />

      <div className="flex flex-col items-center gap-7 w-full">
        <div className="flex flex-col items-center w-full">
          <h1 className="text-3xl sm:text-4xl lg:text-[clamp(2rem,5vw,56px)] lg:leading-[64px] font-normal text-black text-center whitespace-nowrap">
            meet your{" "}
            <span className="font-semibold text-primary">second self</span>
          </h1>
          <p className="text-base sm:text-lg lg:text-2xl font-normal text-black text-center mt-1">
            an AI that lives in your notch, thinks like you, and handles tasks
            while you live your life.
          </p>
        </div>

        {error && (
          <p className="text-red-500 text-sm text-center">{error}</p>
        )}

        <div className="flex flex-col items-center gap-3 w-full">
          <Button onClick={handleClick} disabled={loading}>
            {loading ? "signing in..." : "let\u0027s build you"}
          </Button>
          <button
            onClick={handleSkipAuth}
            className="text-sm text-black/40 hover:text-black/60 transition-colors underline underline-offset-2"
          >
            try without sign-in (web search only)
          </button>
        </div>
      </div>
    </div>
  );
}
