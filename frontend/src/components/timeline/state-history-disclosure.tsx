"use client";
// 役割: state種別記憶の、supersededされた過去の値を折りたたみ表示する。

import { ChevronDownIcon } from "lucide-react";
import { useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui";
import type { StateHistoryEntry } from "@/lib/timeline/transform";
import { cn } from "@/lib/utils";

type StateHistoryDisclosureProps = {
  history: StateHistoryEntry[];
};

export function StateHistoryDisclosure({ history }: StateHistoryDisclosureProps) {
  const [open, setOpen] = useState(false);

  if (history.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mt-3">
      <CollapsibleTrigger
        className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition hover:text-foreground"
      >
        <ChevronDownIcon
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
        />
        過去の履歴を見る({history.length}件)
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-2 border-l-2 border-border pl-4">
        {history.map((entry) => (
          <div key={entry.id} className="text-xs leading-6 text-muted-foreground">
            <p className="whitespace-pre-wrap break-words text-foreground/85">{entry.value}</p>
            <p className="mt-0.5">
              有効開始: {entry.validFromLabel}
              {entry.supersededAtLabel ? ` ・ 置き換え: ${entry.supersededAtLabel}` : ""}
            </p>
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}
