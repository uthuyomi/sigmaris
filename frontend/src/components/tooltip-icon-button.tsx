"use client";
// 役割: ツールチップ付きアイコンボタンの共通Reactコンポーネント。


import { ComponentPropsWithRef, forwardRef } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type TooltipIconButtonProps = ComponentPropsWithRef<typeof Button> & {
  tooltip: string;
};

export const TooltipIconButton = forwardRef<
  HTMLButtonElement,
  TooltipIconButtonProps
>(({ children, tooltip, className, ...rest }, ref) => {
  return (
    <Button
      ref={ref}
      variant="ghost"
      size="icon"
      title={tooltip}
      aria-label={tooltip}
      className={cn("size-8 rounded-full p-1", className)}
      {...rest}
    >
      {children}
    </Button>
  );
});

TooltipIconButton.displayName = "TooltipIconButton";
