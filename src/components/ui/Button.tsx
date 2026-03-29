import ArrowIcon from "./ArrowIcon";

interface ButtonProps {
  children: string;
  onClick?: () => void;
  disabled?: boolean;
  showArrow?: boolean;
  icon?: React.ReactNode;
  variant?: "outline" | "primary";
}

export default function Button({ children, onClick, disabled = false, showArrow = true, icon, variant = "outline" }: ButtonProps) {
  const base = "rounded-[15px] px-4 py-3 flex items-center justify-center gap-2 text-lg md:text-2xl font-normal transition-opacity hover:opacity-80 active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:opacity-40";
  const variants = {
    outline: "border border-black text-black",
    primary: "bg-primary text-white",
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${variants[variant]}`}
    >
      {icon}
      {children}
      {showArrow && <ArrowIcon className="w-5 h-5 md:w-6 md:h-6" />}
    </button>
  );
}
