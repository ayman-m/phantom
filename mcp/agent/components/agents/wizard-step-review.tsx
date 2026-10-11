"use client";

export interface WizardStepReviewProps {
  name: string;
  description: string;
  model: string;
  selectedTools: string[];
  systemPrompt: string;
  creating: boolean;
  error: string | null;
  onCreate: () => void;
}

export function WizardStepReview({
  name,
  description,
  model,
  selectedTools,
  systemPrompt,
  creating,
  error,
  onCreate,
}: WizardStepReviewProps) {
  const isValid = name.trim().length > 0;

  return (
    <div className="space-y-6">
      <p className="text-sm text-on-surface-variant">
        Review the agent configuration below, then create.
      </p>

      {/* Summary Card */}
      <div className="space-y-4">
        <ReviewField label="Name" value={name || "Unnamed agent"} />
        <ReviewField
          label="Description"
          value={description || "No description"}
        />
        <ReviewField label="Model" value={model || "Default model"} />
        <ReviewField
          label="Tools"
          value={
            selectedTools.length > 0
              ? selectedTools.join(", ")
              : "No tools selected"
          }
        />
        <div>
          <span className="block text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60 mb-1">
            System Prompt
          </span>
          <div className="p-3 rounded-lg bg-white/5 border border-white/10">
            <pre className="text-xs text-on-surface font-mono whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
              {systemPrompt || "No system prompt configured"}
            </pre>
          </div>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div
          className="p-4 rounded-lg bg-error/10 border border-error/20 text-error text-sm"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* Create Button */}
      <button
        type="button"
        onClick={onCreate}
        disabled={!isValid || creating}
        className="w-full py-3 rounded-lg font-label font-bold text-sm uppercase tracking-widest transition-all disabled:opacity-50 disabled:cursor-not-allowed bg-gradient-to-r from-[#1963B3] to-[#2D8DF0] text-on-surface hover:shadow-[0_0_20px_rgba(25,99,179,0.4)] active:scale-[0.98]"
        aria-label="Create agent"
      >
        {creating ? (
          <span className="flex items-center justify-center gap-2">
            <span className="material-symbols-outlined animate-spin text-base">
              progress_activity
            </span>
            Creating Agent...
          </span>
        ) : (
          "Create Agent"
        )}
      </button>
    </div>
  );
}

function ReviewField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-4 py-3 border-b border-white/5">
      <span className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant/60 w-24 flex-shrink-0 pt-0.5">
        {label}
      </span>
      <span className="text-sm text-on-surface">{value}</span>
    </div>
  );
}
