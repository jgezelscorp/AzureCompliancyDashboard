import type { BreakdownRow } from "./policyTypes";

/** Where a domain assignment came from, from most to least trustworthy. Mirrors backend CONFIDENCES. */
export const CONFIDENCES = ["override", "source", "derived-high", "derived-low", "unmapped"] as const;
export type Confidence = (typeof CONFIDENCES)[number];

export interface TaxonomyDomain {
  id: string;
  label: string;
  frameworks: Record<string, { id: string; label: string }[]>;
}

export interface Taxonomy {
  taxonomyVersion: number;
  domains: TaxonomyDomain[];
  frameworks: Record<string, { label: string; kind: string }>;
  confidence: Record<string, string>;
  disclaimer: string;
  labels: string[];
}

export interface MachineDomainTally {
  checks: number;
  machines: number;
  passed: number;
  total: number;
  percent: number | null;
}

export interface DomainRow {
  domain: string;
  label: string;
  policy: BreakdownRow | null;
  /** Keyed by baseline family; families are never merged into one rate. */
  machine: Record<string, MachineDomainTally>;
  frameworks: Record<string, string[]>;
}

export interface ProvenanceMix {
  total: number;
  byConfidence: Record<Confidence, number>;
  unmapped: number;
  unmappedPercent: number | null;
  sourcePercent: number | null;
  derivedPercent: number | null;
  overridePercent: number | null;
}

export interface Provenance {
  policies: ProvenanceMix;
  checks: ProvenanceMix;
}

export interface DomainOverview {
  taxonomyVersion: number;
  snapshotAt: string | null;
  machineSnapshotAt: string | null;
  domains: DomainRow[];
  provenance: Provenance;
  grain: { policy: string; machine: string };
  disclaimer: string;
  filters: Record<string, unknown>;
  labels: string[];
}

export interface FrameworkFamily {
  family: string;
  label: string;
  domains: string[];
  policies: number;
  evaluations: number;
  compliant: number;
  nonCompliant: number;
  percent: number | null;
  checks: number;
  checksFailing: number;
}

export interface Frameworks {
  taxonomyVersion: number;
  frameworks: { framework: string; label: string; kind: string; families: FrameworkFamily[] }[];
  additive: boolean;
  note: string;
  disclaimer: string;
  snapshotAt: string | null;
}

export interface QueueRow {
  kind: "policy" | "check";
  key: string;
  name: string;
  family: string | null;
  category: string | null;
  domain: string;
  domainSource: string;
  domainConfidence: Confidence;
  evaluations: number;
  nonCompliant: number;
  suggestedDomain: string | null;
  domainLabel: string;
}

export interface Queue {
  total: number;
  limit: number;
  offset: number;
  summary: { policy: number; check: number };
  confidences: string[];
  rows: QueueRow[];
  taxonomyVersion: number;
  snapshotAt: string | null;
}

export interface QueueParams {
  kind: "all" | "policy" | "check";
  confidence: string[];
  q: string;
  limit: number;
  offset: number;
}

export interface DomainCheckRow {
  checkKey: string;
  name: string;
  family: string;
  category: string | null;
  domain: string;
  domainSource: string;
  domainConfidence: Confidence;
  domainVersion: number | null;
  machinesPassed: number;
  machinesFailed: number;
}

export interface DomainChecks {
  domain: string;
  domainLabel: string;
  total: number;
  rows: DomainCheckRow[];
  grain: string;
  taxonomyVersion: number;
}

export interface OverrideRow {
  id: number;
  target: "policy" | "check";
  kind: string;
  pattern: string;
  domain: string;
  note: string | null;
  createdBy: string;
  createdAt: string;
}

export interface Overrides {
  overrides: OverrideRow[];
  repoOverrides: number;
  gateEnabled: boolean;
  editing: string;
  taxonomyVersion: number;
}

export interface OverrideRequest {
  target: "policy" | "check";
  pattern: string;
  domain: string;
  note?: string;
}

export interface Capabilities {
  canEditSharedConfig: boolean;
  reason: string;
}
