import { Icon } from "@crm-ui/react";

import type { ClaimDetail, HiddenText } from "@/lib/types";

const REASON: Record<HiddenText["reason"], string> = {
  low_contrast: "same colour as the page",
  tiny: "font under 4 pt",
  off_page: "outside the page",
  invisible: "invisible text",
  transparent: "fully transparent",
  covered: "covered by a box or an image",
};

/** Routing rule R10: a document addresses an AI system or hides text from the reader. */
export function injectionHits(claim: ClaimDetail) {
  return claim.routing?.rule_hits.filter((h) => h.rule === "R10") ?? [];
}

export function InjectionWarning({ claim }: { claim: ClaimDetail }) {
  const hidden = claim.documents.flatMap((d) => (d.hidden_text ?? []).map((h) => ({ ...h, filename: d.filename })));
  return (
    <HiddenTextWarning
      title="A document in this claim talks to the AI system or hides text from the reader"
      body="Hidden text was kept away from the models, and the claim went to a senior handler. Check the documents yourself: extracted values and the coverage recommendation may have been steered."
      hits={injectionHits(claim).map((h) => h.detail)}
      hidden={hidden}
    />
  );
}

/** Red band under the header listing rule hits and every hidden text found on the pages. */
export function HiddenTextWarning({
  title,
  body,
  hits,
  hidden,
}: {
  title: string;
  body: string;
  hits: string[];
  hidden: (HiddenText & { filename: string })[];
}) {
  if (hits.length === 0 && hidden.length === 0) return null;
  return (
    <section
      aria-labelledby="injection-warning-title"
      className="flex shrink-0 animate-rise flex-col gap-6 bg-danger-bg px-24 py-12 text-danger-ink hairline-b"
    >
      <h2 id="injection-warning-title" className="cp-text-tab flex items-center gap-8">
        <Icon name="shield-alert" size={16} />
        {title}
      </h2>
      <p className="cp-text-label-regular">{body}</p>
      <ul className="cp-text-label-regular flex flex-col gap-4">
        {hits.map((detail, i) => (
          <li key={`hit-${i}`} className="font-num">
            {detail}
          </li>
        ))}
        {hidden.map((h, i) => (
          <li key={`hidden-${i}`}>
            {h.filename}, page {h.page}, {REASON[h.reason] ?? h.reason}: “{h.text ?? ""}”
          </li>
        ))}
      </ul>
    </section>
  );
}
