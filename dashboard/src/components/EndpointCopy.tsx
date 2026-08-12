"use client";

import { useState } from "react";

export function EndpointCopy({ label, url }: { label: "Spend" | "Status"; url: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard?.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      className="endpoint-copy"
      aria-label={`Copy ${label} endpoint`}
      onClick={() => void copy()}
    >
      <code className="mono">{url}</code>
      <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
    </button>
  );
}
