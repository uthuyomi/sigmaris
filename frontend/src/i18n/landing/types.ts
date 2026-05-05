export type LandingUseCaseIcon = "image" | "sheets" | "route" | "calendar";

export type LandingCopy = {
  tagline: string;
  login: string;
  previewEyebrow: string;
  previewTitle: string;
  previewItems: Array<[string, string, string]>;
  heroEyebrow: string;
  heroTitle: string;
  heroBody: string;
  heroCards: Array<[string, string]>;
  primaryCta: string;
  secondaryCta: string;
  detailsEyebrow: string;
  detailsTitle: string;
  detailsBody: string;
  useCases: Array<{
    icon: LandingUseCaseIcon;
    title: string;
    text: string;
  }>;
  workflowEyebrow: string;
  workflowTitle: string;
  workflowBody: string;
  workflow: Array<{
    step: string;
    title: string;
    text: string;
  }>;
  examplesEyebrow: string;
  examplesTitle: string;
  examples: string[];
  audienceTitle: string;
  audienceItems: string[];
};
