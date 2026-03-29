export default function Pill({ children }: { children: string }) {
  return (
    <span className="border border-primary-dark rounded-[15px] px-2 py-0.5 text-sm font-normal text-black text-center whitespace-nowrap">
      {children}
    </span>
  );
}
