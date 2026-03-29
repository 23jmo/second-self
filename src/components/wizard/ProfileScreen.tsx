import MascotFace from "@/components/mascot/MascotFace";
import Button from "@/components/ui/Button";
import Pill from "@/components/ui/Pill";

interface ProfileScreenProps {
  name: string;
  role: string;
  onNext: () => void;
}

export default function ProfileScreen({ name, role, onNext }: ProfileScreenProps) {
  return (
    <div className="flex flex-col items-center gap-6 w-full max-w-[681px] px-4">
      <MascotFace className="w-36 sm:w-44 md:w-52" />

      <div className="flex flex-col items-center gap-7 w-full">
        <div className="flex flex-col items-center w-full text-center">
          <h1 className="text-3xl sm:text-4xl lg:text-[56px] lg:leading-[64px] font-normal text-black">
            your{" "}
            <span className="font-semibold text-primary">second self</span>{" "}
            is ready
          </h1>
          <p className="text-base sm:text-lg lg:text-2xl font-normal text-black mt-1">
            here&apos;s what it knows about you.
          </p>
        </div>

        {/* Profile card */}
        <div className="border-3 border-primary rounded-[15px] w-full max-w-[408px] p-6 sm:p-8">
          <div className="flex flex-col gap-4 sm:gap-5">
            <ProfileRow label="name" value={name || "jazlynn"} />
            <ProfileRow label="role" value={role || "explorer"} />
            <div className="flex items-center gap-4 sm:gap-8">
              <span className="text-sm sm:text-base font-normal text-black w-10 text-center shrink-0">tone</span>
              <div className="flex gap-3 sm:gap-4 flex-wrap">
                <Pill>curious</Pill>
                <Pill>witty</Pill>
                <Pill>chill</Pill>
              </div>
            </div>
            <div className="flex items-center gap-4 sm:gap-8">
              <span className="text-sm sm:text-base font-normal text-black w-10 text-center shrink-0">tools</span>
              <div className="flex gap-3 sm:gap-4 flex-wrap">
                <Pill>notion</Pill>
                <Pill>slack</Pill>
                <Pill>gmail</Pill>
              </div>
            </div>
          </div>
        </div>

        <Button onClick={onNext}>launch your twin</Button>
      </div>
    </div>
  );
}

function ProfileRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-4 sm:gap-8">
      <span className="text-sm sm:text-base font-normal text-black w-10 text-center shrink-0">{label}</span>
      <span className="text-sm sm:text-base font-normal text-black">{value}</span>
    </div>
  );
}
