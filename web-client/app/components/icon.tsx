import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react";

import { cn } from "~/lib/utils";

export function makeIcon(data: IconSvgElement) {
  return function Icon({ className, ...props }: { className?: string }) {
    return (
      <HugeiconsIcon
        icon={data}
        className={cn("size-4", className)}
        {...props}
      />
    );
  };
}
