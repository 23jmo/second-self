"use client";

import { useUser } from "@auth0/nextjs-auth0";
import MascotFullBody from "@/components/mascot/MascotFullBody";
import Button from "@/components/ui/Button";

interface WelcomeScreenProps {
  onNext: () => void;
  onSession: (sessionId: string, email: string) => void;
}

export default function WelcomeScreen({ onNext, onSession }: WelcomeScreenProps) {
  const { user, isLoading } = useUser();

  const handleClick = () => {
    if (user) {
      // Already logged in — proceed directly
      const email = user.email ?? "";
      onSession("auth0", email);
      onNext();
    } else {
      // Redirect to Auth0 login
      window.location.href = "/auth/login?returnTo=/";
    }
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

        <Button onClick={handleClick} disabled={isLoading}>
          {isLoading ? "signing in..." : "let\u0027s build you"}
        </Button>
      </div>
    </div>
  );
}
