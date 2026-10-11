"use client";

import type { ModelInfo } from "@/lib/api/types";

export interface WizardStepModelProps {
  models: ModelInfo[];
  selectedModel: string;
  onModelChange: (model: string) => void;
  loading: boolean;
}

export function WizardStepModel({
  models,
  selectedModel,
  onModelChange,
  loading,
}: WizardStepModelProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="flex items-center gap-3 text-on-surface-variant">
          <span className="material-symbols-outlined animate-spin">progress_activity</span>
          <span className="text-sm">Loading available models...</span>
        </div>
      </div>
    );
  }

  if (models.length === 0) {
    return (
      <div className="text-center py-12">
        <span className="material-symbols-outlined text-4xl text-on-surface-variant mb-2 block">
          warning
        </span>
        <p className="text-sm text-on-surface-variant">
          No models available. Configure provider keys in Settings first.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <label
        htmlFor="model-select"
        className="block text-xs font-label uppercase tracking-widest text-on-surface-variant mb-2"
      >
        Default Model
      </label>

      <select
        id="model-select"
        value={selectedModel}
        onChange={(e) => onModelChange(e.target.value)}
        className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-on-surface focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors appearance-none cursor-pointer"
        aria-label="Select model"
      >
        <option value="" className="bg-[#1a1a2e]">
          Select a model...
        </option>
        {models.map((m) => (
          <option
            key={`${m.provider}-${m.model}`}
            value={m.model}
            className="bg-[#1a1a2e]"
          >
            {m.displayName || m.model} ({m.provider})
          </option>
        ))}
      </select>

      {/* Selected Model Details */}
      {selectedModel && (
        <SelectedModelCard
          model={models.find((m) => m.model === selectedModel)}
        />
      )}
    </div>
  );
}

function SelectedModelCard({ model }: { model: ModelInfo | undefined }) {
  if (!model) return null;

  return (
    <div
      className="mt-4 p-4 rounded-xl border border-primary/20 bg-primary/5"
      aria-label="Selected model details"
    >
      <div className="flex items-center gap-3 mb-3">
        <span className="material-symbols-outlined text-primary">
          {model.supportsThinking ? "psychology" : "auto_awesome"}
        </span>
        <span className="font-headline font-bold">
          {model.displayName || model.model}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
        <div>
          <span className="text-on-surface-variant block mb-0.5">Provider</span>
          <span className="font-medium">{model.provider}</span>
        </div>
        <div>
          <span className="text-on-surface-variant block mb-0.5">Context</span>
          <span className="font-medium">
            {model.contextWindow >= 1_000_000
              ? `${(model.contextWindow / 1_000_000).toFixed(0)}M`
              : `${(model.contextWindow / 1_000).toFixed(0)}K`}{" "}
            tokens
          </span>
        </div>
        <div>
          <span className="text-on-surface-variant block mb-0.5">Thinking</span>
          <span className={model.supportsThinking ? "text-secondary" : "text-on-surface-variant"}>
            {model.supportsThinking ? "Supported" : "No"}
          </span>
        </div>
        <div>
          <span className="text-on-surface-variant block mb-0.5">Tools</span>
          <span className={model.supportsTools ? "text-secondary" : "text-on-surface-variant"}>
            {model.supportsTools ? "Supported" : "No"}
          </span>
        </div>
      </div>
    </div>
  );
}
