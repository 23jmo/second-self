"use client";

import { useEffect, useState } from "react";
import { GoogleAuthProvider, signInWithPopup, signInWithRedirect, getRedirectResult } from "firebase/auth";
import { auth } from "@/lib/firebase";
import { useFirebaseUser } from "@/hooks/useFirebaseUser";
import { postAuthCallback } from "@/lib/api";
import MascotFullBody from "@/components/mascot/MascotFullBody";
import Button from "@/components/ui/Button";

const provider = new GoogleAuthProvider();
provider.addScope("https://www.googleapis.com/auth/gmail.readonly");
provider.addScope("https://www.googleapis.com/auth/gmail.send");
provider.addScope("https://www.googleapis.com/auth/calendar.readonly");
provider.addScope("https://www.googleapis.com/auth/calendar.events");
provider.addScope("https://www.googleapis.com/auth/documents");
provider.addScope("https://www.googleapis.com/auth/presentations");
provider.addScope("https://www.googleapis.com/auth/drive.file");

/** Extract the Google OAuth access token from a Firebase sign-in result. */
function getGoogleAccessToken(result: Awaited<ReturnType<typeof signInWithPopup>>): string {
  const credential = GoogleAuthProvider.credentialFromResult(result);
  return credential?.accessToken ?? "";
}

/** Exchange Firebase tokens with the backend to create a real session. */
async function exchangeTokens(result: Awaited<ReturnType<typeof signInWithPopup>>): Promise<{ sessionId: string; email: string }> {
  const email = result.user.email ?? "";
  const name = result.user.displayName ?? email;
  const idToken = await result.user.getIdToken();
  const googleAccessToken = getGoogleAccessToken(result);

  const resp = await postAuthCallback(idToken, googleAccessToken, email, name);
  return { sessionId: resp.session_id, email };
}

interface WelcomeScreenProps {
  onNext: () => void;
  onSession: (sessionId: string, email: string) => void;
}

export default function WelcomeScreen({ onNext, onSession }: WelcomeScreenProps) {
  const { user, isLoading } = useFirebaseUser();
  const [signingIn, setSigningIn] = useState(false);

  // Handle redirect result when returning from Google sign-in
  useEffect(() => {
    getRedirectResult(auth).then(async (result) => {
      if (result) {
        try {
          const { sessionId, email } = await exchangeTokens(result);
          onSession(sessionId, email);
          onNext();
        } catch (err) {
          console.error("Token exchange failed (redirect):", err);
        }
      }
    }).catch((err: unknown) => {
      console.error("Firebase redirect error:", err);
    });
  }, [onSession, onNext]);

  const handleClick = async () => {
    setSigningIn(true);
    try {
      const result = await signInWithPopup(auth, provider);
      const { sessionId, email } = await exchangeTokens(result);
      onSession(sessionId, email);
      onNext();
    } catch (err: unknown) {
      const firebaseErr = err as { code?: string };
      if (firebaseErr.code === "auth/popup-closed-by-user") {
        setSigningIn(false);
        return;
      }
      // Popup blocked — fall back to redirect
      if (firebaseErr.code === "auth/popup-blocked") {
        await signInWithRedirect(auth, provider);
        return;
      }
      console.error("Firebase sign-in error:", err);
      setSigningIn(false);
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

        <div className="flex flex-col items-center gap-3 w-full">
          <Button onClick={handleClick} disabled={isLoading || signingIn}>
            {isLoading || signingIn ? "signing in..." : "let\u0027s build you"}
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
