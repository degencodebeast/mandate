"use client";

import { useState } from "react";

type RestCommandCopyProps =
  | {
      kind: "spend";
      url: string;
      serviceUrl: string;
      amount: string;
    }
  | {
      kind: "status";
      url: string;
    };

function shellSingleQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function spendCommand(url: string, serviceUrl: string, amount: string): string {
  const body = JSON.stringify(
    {
      task_id: "demo-search-001",
      purpose: "Buy one search result",
      service_url: serviceUrl,
      amount,
    },
    null,
    2,
  );
  return `curl --fail-with-body --show-error \\
  --request POST \\
  --header "Authorization: Bearer $PRIVY_ACCESS_TOKEN" \\
  --header "Content-Type: application/json" \\
  --data ${shellSingleQuote(body)} \\
  "${url}"`;
}

function statusCommand(url: string): string {
  return `curl --fail-with-body --show-error \\
  --request GET \\
  --header "Authorization: Bearer $PRIVY_ACCESS_TOKEN" \\
  "${url}"`;
}

export function RestCommandCopy(props: RestCommandCopyProps) {
  const [copied, setCopied] = useState(false);
  const label = props.kind === "spend" ? "Spend" : "Status";
  const command =
    props.kind === "spend"
      ? spendCommand(props.url, props.serviceUrl, props.amount)
      : statusCommand(props.url);

  const copy = async () => {
    await navigator.clipboard?.writeText(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="stack-2">
      <span className="card-meta">
        {props.kind === "spend"
          ? "POST · Spend · Bearer token required"
          : "GET · Status · Bearer token required"}
      </span>
      <button
        type="button"
        className="endpoint-copy rest-command-copy"
        aria-label={`Copy ${label} command`}
        onClick={() => void copy()}
      >
        <code className="mono">{command}</code>
        <span aria-live="polite">{copied ? "Copied" : "Copy command"}</span>
      </button>
    </div>
  );
}
