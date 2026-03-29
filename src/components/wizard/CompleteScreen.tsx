import MascotFullBodyLookUp from "@/components/mascot/MascotFullBodyLookUp";
import Button from "@/components/ui/Button";
import DownloadIcon from "@/components/ui/DownloadIcon";

interface CompleteScreenProps {
  name: string;
}

export default function CompleteScreen({ name }: CompleteScreenProps) {
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
          your second self lives in the notch.
          <br />
          tap it anytime to give a command.
        </p>
      </div>

      <a href="#" className="mt-2">
        <Button showArrow={false} variant="primary" icon={<DownloadIcon className="w-5 h-5 md:w-6 md:h-6" />}>download second self</Button>
      </a>
    </div>
  );
}
