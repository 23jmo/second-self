import MascotFullBodyLookUp from "@/components/mascot/MascotFullBodyLookUp";
import Button from "@/components/ui/Button";

interface CompleteScreenProps {
  name: string;
  onNext: () => void;
}

export default function CompleteScreen({ name, onNext }: CompleteScreenProps) {
  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[615px] px-4">
      {/* Name tag */}
      <div className="bg-[#FBFFD4] border border-[rgba(156,161,97,0.8)] rounded-[15px] px-9 py-3 shadow-[0px_4px_4px_rgba(0,0,0,0.25)]">
        <p className="text-lg sm:text-xl lg:text-2xl font-normal text-primary-dark text-center whitespace-nowrap">
          {name}
        </p>
      </div>

      {/* Mascot */}
      <MascotFullBodyLookUp className="w-36 sm:w-44 md:w-52" />

      {/* Text */}
      <div className="flex flex-col items-center w-full">
        <h1 className="text-3xl sm:text-4xl lg:text-[56px] lg:leading-[64px] font-normal text-black text-center">
          you&apos;re all set{" "}
          <span className="font-semibold text-primary">twin</span>
        </h1>
        <p className="text-base sm:text-lg lg:text-2xl font-normal text-black text-center mt-1">
          your second self is ready to go.
          <br />
          start chatting to put it to work.
        </p>
      </div>

      <div className="mt-2">
        <Button onClick={onNext}>start chatting</Button>
      </div>
    </div>
  );
}
