interface InputProps {
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  onFocus?: () => void;
  onBlur?: () => void;
}

export default function Input({ placeholder, value, onChange, onFocus, onBlur }: InputProps) {
  return (
    <input
      type="text"
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onFocus={onFocus}
      onBlur={onBlur}
      className="w-full border border-black rounded-[15px] px-4 py-3 text-lg md:text-2xl font-normal text-black placeholder:text-black/40 outline-none focus:border-primary transition-colors"
    />
  );
}
