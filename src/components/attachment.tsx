import { AttachmentPrimitive } from "@assistant-ui/react";
import { PaperclipIcon, XIcon } from "lucide-react";
import type { FC } from "react";

export const ComposerAttachments: FC = () => {
  return (
    <AttachmentPrimitive.Root className="flex items-center gap-2 rounded-full border border-white/10 bg-white/8 px-3 py-2 text-xs text-stone-200">
      <PaperclipIcon className="size-3.5 text-stone-300" />
      <span className="max-w-40 truncate">
        <AttachmentPrimitive.Name />
      </span>
      <AttachmentPrimitive.Remove className="inline-flex size-5 items-center justify-center rounded-full text-stone-400 transition hover:bg-white/10 hover:text-stone-100">
        <XIcon className="size-3.5" />
      </AttachmentPrimitive.Remove>
    </AttachmentPrimitive.Root>
  );
};

export const UserMessageAttachments: FC = () => {
  return (
    <AttachmentPrimitive.Root className="inline-flex max-w-full items-center gap-2 rounded-full border border-stone-900/10 bg-white/70 px-3 py-2 text-xs text-stone-700">
      <PaperclipIcon className="size-3.5 text-stone-500" />
      <span className="truncate">
        <AttachmentPrimitive.Name />
      </span>
    </AttachmentPrimitive.Root>
  );
};
