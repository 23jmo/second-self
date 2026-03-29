"use client";

import MascotFace from "@/components/mascot/MascotFace";
import Button from "@/components/ui/Button";

interface CompleteScreenProps {
  name: string;
  onNext: () => void;
}

export default function CompleteScreen({ name, onNext }: CompleteScreenProps) {
  return (
    <div className="flex flex-col items-center gap-6 w-full max-w-[615px] px-4">
      <MascotFace className="w-28 sm:w-36" />

      <div className="flex flex-col items-center gap-3 w-full">
        <h1 className="text-3xl sm:text-4xl font-semibold text-black text-center">
          you&apos;re all set, {name || "friend"}
        </h1>
        <p className="text-base sm:text-lg text-gray-600 text-center">
          your second self is ready. let&apos;s start chatting.
        </p>
      </div>

      <Button onClick={onNext}>start chatting</Button>
    </div>
  );
}
