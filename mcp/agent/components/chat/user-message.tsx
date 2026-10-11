import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/stores/chat";

export interface UserMessageProps {
  message: ChatMessage;
  className?: string;
}

export function UserMessage({ message, className }: UserMessageProps) {
  const text = message.text?.trim();

  return (
    <div className={cn("flex justify-end", className)}>
      <div className="max-w-[70%] bg-primary-container text-on-primary-container p-5 rounded-2xl rounded-tr-none shadow-xl">
        <p className="text-sm leading-relaxed">
          {text || "\u00A0"}
        </p>
      </div>
    </div>
  );
}
