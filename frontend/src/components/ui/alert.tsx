import type { HTMLAttributes } from "react";

import { cn } from "../../lib/utils";

export function Alert({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-xl border border-rose-400/25 bg-rose-400/10 p-4 text-sm text-rose-100",
        className,
      )}
      {...props}
    />
  );
}