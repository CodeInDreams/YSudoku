import { cn } from "../../lib/utils";
export function Badge({ className, variant = "secondary", ...props }) {
  const styles = {
    secondary: "bg-secondary text-secondary-foreground",
    outline: "border border-input text-foreground",
    success: "bg-emerald-50 text-emerald-700 border border-emerald-200",
    warning: "bg-amber-50 text-amber-700 border border-amber-200",
    destructive: "bg-rose-50 text-rose-700 border border-rose-200",
  }[variant];
  return <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium", styles, className)} {...props} />;
}
