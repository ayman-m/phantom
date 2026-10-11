"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

export interface RetryButtonProps {
  label?: string;
  className?: string;
}

export function RetryButton({
  label = "Retry",
  className,
}: RetryButtonProps) {
  const router = useRouter();

  return (
    <Button
      type="button"
      variant="outline"
      className={className}
      onClick={() => router.refresh()}
    >
      {label}
    </Button>
  );
}
