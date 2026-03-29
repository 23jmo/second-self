import MascotFace from "@/components/mascot/MascotFace";
import Button from "@/components/ui/Button";
import Pill from "@/components/ui/Pill";
import ArrowIcon from "@/components/ui/ArrowIcon";
import type { SecondSelfProfile } from "@/lib/api";

interface ProfileScreenProps {
  name: string;
  role: string;
  profile: SecondSelfProfile | null;
  onNext: () => void;
  onBack?: () => void;
}

export default function ProfileScreen({ name, role, profile, onNext, onBack }: ProfileScreenProps) {
  const isKnown = (v: string | undefined) => v && v.toLowerCase() !== "unknown";

  // Identity
  const displayName = profile?.identity?.name || name;
  const displayRole = isKnown(profile?.identity?.role) ? profile!.identity.role : isKnown(role) ? role : null;
  const displayCompany = isKnown(profile?.identity?.company) ? profile!.identity.company : null;

  // Tone pills
  const tonePills = profile?.voice?.tone
    ? profile.voice.tone.split(/[,/&]+/).map((t) => t.trim()).filter(Boolean)
    : ["friendly"];

  // Focus areas from active projects
  const focusPills = profile?.context?.active_projects?.slice(0, 4) ?? [];

  // Signature phrases
  const phrasePills = profile?.voice?.signature_phrases?.slice(0, 3) ?? [];

  // Response style
  const responseStyle = profile?.behavior?.response_style;
  const workHours = profile?.behavior?.work_hours;

  return (
    <div className="relative flex flex-col items-center gap-6 w-full max-w-[681px] px-4">
      {onBack && (
        <button
          onClick={onBack}
          className="absolute top-0 left-4 flex items-center gap-1 text-sm text-black/40 hover:text-black/60 transition-colors"
        >
          <ArrowIcon className="w-4 h-4 rotate-180" />
          back
        </button>
      )}
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
            <ProfileRow label="name" value={displayName} />
            {displayRole && (
              <ProfileRow label="role" value={displayCompany ? `${displayRole} @ ${displayCompany}` : displayRole} />
            )}
            <PillRow label="tone" items={tonePills} />
            {focusPills.length > 0 && <PillRow label="focus" items={focusPills} />}
            {phrasePills.length > 0 && <PillRow label="vocab" items={phrasePills} />}
            {isKnown(responseStyle) && <ProfileRow label="style" value={responseStyle!} />}
            {isKnown(workHours) && <ProfileRow label="hours" value={workHours!} />}
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
      <span className="text-sm sm:text-base font-normal text-black w-14 text-right shrink-0">{label}</span>
      <span className="text-sm sm:text-base font-normal text-black">{value}</span>
    </div>
  );
}

function PillRow({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="flex items-start gap-4 sm:gap-8">
      <span className="text-sm sm:text-base font-normal text-black w-14 text-right shrink-0 pt-0.5">{label}</span>
      <div className="flex gap-2 sm:gap-3 flex-wrap">
        {items.map((t) => (
          <Pill key={t}>{t}</Pill>
        ))}
      </div>
    </div>
  );
}
