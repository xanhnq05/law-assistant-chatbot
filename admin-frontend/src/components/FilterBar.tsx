import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface FilterBarProps {
  search: string;
  onSearchChange: (v: string) => void;
  searchPlaceholder?: string;
  rightSlot?: React.ReactNode;
  className?: string;
}

/**
 * Light-theme search bar with clear button.
 * `rightSlot` cho phép chèn thêm control bên phải (VD: button "Thêm mới").
 */
export default function FilterBar({
  search,
  onSearchChange,
  searchPlaceholder = "Tìm kiếm...",
  rightSlot,
  className,
}: FilterBarProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [focused, setFocused] = useState(false);

  // Keyboard shortcut: "/" focus search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.key === "/" &&
        document.activeElement?.tagName !== "INPUT" &&
        document.activeElement?.tagName !== "TEXTAREA"
      ) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const showClear = useMemo(() => search.length > 0, [search]);

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div
        className={cn(
          "flex items-center gap-2 flex-1 max-w-xl bg-white border rounded-xl px-3 py-2 transition",
          focused
            ? "border-blue-400 ring-2 ring-blue-100"
            : "border-slate-200 hover:border-slate-300"
        )}
      >
        <Search className="w-4 h-4 text-slate-400 shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={searchPlaceholder}
          className="flex-1 bg-transparent text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
        />
        {showClear && (
          <button
            type="button"
            onClick={() => onSearchChange("")}
            className="text-slate-400 hover:text-slate-600 transition"
            aria-label="Xoá tìm kiếm"
          >
            <X className="w-4 h-4" />
          </button>
        )}
        <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono text-slate-400 bg-slate-50 border border-slate-200">
          /
        </kbd>
      </div>
      {rightSlot}
    </div>
  );
}
