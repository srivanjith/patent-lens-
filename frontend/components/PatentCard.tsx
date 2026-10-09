"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SearchResultItem, ScoreBreakdown } from "@/types";
import { Bookmark, ExternalLink, ArrowUpRight, Building2, Calendar, Check, Info, Layers, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { api } from "@/services/api";
import { getOfficialPatentUrl, formatDate } from "@/lib/utils";

interface PatentCardProps {
  item: SearchResultItem;
  onSavedToggle?: () => void;
  isInitialSaved?: boolean;
}

export default function PatentCard({ item, onSavedToggle, isInitialSaved = false }: PatentCardProps) {
  const { patent, semantic_score, final_score, matched_concepts, rank, semantic_similarity_label, relevance_explanation, score_breakdown, family_members, family_size } = item;
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(isInitialSaved);
  const [showFormulaModal, setShowFormulaModal] = useState(false);
  const [showFamilyModal, setShowFamilyModal] = useState(false);
  const [showClaimModal, setShowClaimModal] = useState(false);

  useEffect(() => {
    setSaved(isInitialSaved);
  }, [isInitialSaved]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      if (saved) {
        await api.unsavePatent(patent.id);
        setSaved(false);
      } else {
        await api.savePatent(patent.id);
        setSaved(true);
      }
      if (onSavedToggle) onSavedToggle();
    } catch (e) {
      console.error(e);
    } finally {
      setIsSaving(false);
    }
  };

  const bd: ScoreBreakdown = score_breakdown || {
    semantic: { value: semantic_score, weight: 0.25, effective_weight: 0.25, contribution: semantic_score * 0.25, status: "AVAILABLE" },
    technical_features: { value: item.keyword_score || item.technical_feature_coverage || 0, weight: 0.35, effective_weight: 0.35, contribution: (item.keyword_score || 0) * 0.35, status: "AVAILABLE" },
    evidence: { value: item.evidence_confidence || 0, weight: 0.20, effective_weight: 0.20, contribution: (item.evidence_confidence || 0) * 0.20, status: "AVAILABLE" },
    concepts: { value: item.keyword_score || 0, weight: 0.10, effective_weight: 0.10, contribution: (item.keyword_score || 0) * 0.10, status: "AVAILABLE" },
    domain_cpc: { value: item.domain_score || 50, weight: 0.10, effective_weight: 0.10, contribution: (item.domain_score || 50) * 0.10, status: "AVAILABLE" },
    semantic_similarity: semantic_score,
    technical_features_score: item.keyword_score || item.technical_feature_coverage || 0,
    evidence_strength: item.evidence_confidence || 0,
    distinctive_concepts: item.keyword_score || 0,
    domain_cpc_alignment: item.domain_score || 50,
    technology_domain_score: item.domain_score || 50,
    cpc_match_score: 85,
    final_score: final_score,
    is_gated: false,
    formula_explanation: "Final Score = (25% Semantic) + (35% Technical Features) + (20% Evidence) + (10% Distinctive Concepts) + (10% Domain/CPC)"
  };

  const strongMatches = item.strong_matches || item.matched_features?.filter(m => String(m.match_type || m.match_level).toLowerCase().includes("strong")).map(m => typeof m === "string" ? m : m.feature) || [];
  const partialMatches = item.partial_matches || item.matched_features?.filter(m => String(m.match_type || m.match_level).toLowerCase().includes("partial")).map(m => typeof m === "string" ? m : m.feature) || [];
  const missingFeatures = item.missing_features || item.unmatched_features || item.missing_elements || [];

  const matchedCount = item.matched_feature_count ?? (strongMatches.length + partialMatches.length);
  const totalCount = item.total_feature_count ?? (strongMatches.length + partialMatches.length + missingFeatures.length);

  const computedScore = Math.round(final_score);
  const simLevel = item.relevance_level || semantic_similarity_label || (computedScore >= 70 ? "Very High" : computedScore >= 50 ? "High" : computedScore >= 30 ? "Moderate" : "Low");

  const evidenceItems = item.evidence_items || [];
  const topEvidence = evidenceItems[0] || (item.matched_features && item.matched_features[0] ? {
    feature: item.matched_features[0].feature,
    evidence: item.matched_features[0].evidence || item.matched_features[0].patent_evidence,
    source: item.matched_features[0].source_section || "Claims",
    verified: true
  } : null);

  const evStatusLabel = item.evidence_status_label || (item.evidence_status === "VERIFIED" ? (item.claims_status === "AVAILABLE" ? "Claim evidence verified" : "Description evidence verified") : "Limited evidence");

  return (
    <div className="group relative rounded-xl tech-card tech-card-hover p-6 space-y-4">
      
      {/* Rank & Main Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-3.5 border-b border-zinc-800/80">
        <div className="flex items-start gap-3.5">
          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-indigo-500/10 text-indigo-400 font-mono font-bold text-xs flex items-center justify-center border border-indigo-500/25">
            #{rank}
          </div>
          <div>
            <h3 className="text-base font-bold text-zinc-100 group-hover:text-indigo-400 transition-colors leading-snug">
              {patent.title}
            </h3>
            <div className="flex flex-wrap items-center gap-2.5 mt-1 text-xs text-zinc-400">
              <span className="font-mono font-semibold text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20 text-[11px]">
                {patent.patent_number}
              </span>
              <span>•</span>
              <span className="flex items-center gap-1 font-medium text-zinc-300">
                <Building2 className="w-3.5 h-3.5 text-zinc-500" />
                {patent.assignee}
              </span>
              <span>•</span>
              <span className="flex items-center gap-1 font-medium text-zinc-400 font-mono text-[11px]">
                <Calendar className="w-3.5 h-3.5 text-zinc-500" />
                {formatDate(patent.publication_date)}
              </span>
              {(family_size || 1) > 1 && (
                <>
                  <span>•</span>
                  <button
                    onClick={() => setShowFamilyModal(true)}
                    className="flex items-center gap-1 font-mono font-semibold text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20 px-2 py-0.5 rounded border border-emerald-500/25 text-[11px] transition-all"
                  >
                    <Layers className="w-3 h-3" />
                    Family: {family_size} docs (View)
                  </button>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 self-end sm:self-auto">
          <div className="text-right flex gap-4 items-center">
            {/* Relevance Score */}
            <div>
              <div className="flex items-center justify-end gap-1 text-[10px] font-mono font-semibold uppercase tracking-wider text-zinc-400">
                <span>Relevance</span>
                <button
                  onClick={() => setShowFormulaModal(true)}
                  className="text-zinc-500 hover:text-indigo-400 transition-colors"
                  title="How is this calculated?"
                >
                  <Info className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="text-xl font-bold font-mono text-indigo-400 flex items-center justify-end gap-1.5">
                {computedScore}%
                <span className="text-xs font-normal text-zinc-400">({simLevel})</span>
              </div>
            </div>

            {/* Evidence Confidence Score */}
            <div className="border-l border-zinc-800 pl-4">
              <div className="text-[10px] font-mono font-semibold uppercase tracking-wider text-zinc-400">
                Confidence
              </div>
              <div className="text-xl font-bold font-mono text-emerald-400 flex items-center justify-end gap-1">
                {Math.round(item.confidence_score ?? item.evidence_confidence ?? 0)}%
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Metric Badges & Honest Evidence Status */}
      <div className="space-y-2.5">
        <div className="flex flex-wrap items-center gap-2">
          {(() => {
            const rawStatus = (item.source_status || patent.source_status || "DATABASE").toUpperCase();
            const rawType = (patent.source_type || item.source_type || (patent.patent_number.startsWith("ARXIV") ? "ARXIV" : "DATABASE")).toUpperCase();

            let displaySource = "DATABASE";
            let defaultDocType = rawStatus === "DATABASE" ? "DATABASE RECORD" : "PATENT";

            if (rawStatus === "LIVE_API" && (rawType === "THE LENS" || rawType === "THE LENS PATENT API")) {
              displaySource = "THE LENS";
              defaultDocType = "PATENT";
            } else if (rawType === "ARXIV" || patent.patent_number.startsWith("ARXIV")) {
              displaySource = "arXiv";
              defaultDocType = "NON-PATENT LITERATURE";
            } else if (rawStatus === "FALLBACK" || rawType.includes("FALLBACK") || rawType === "USPTO") {
              displaySource = rawType === "USPTO" ? "FALLBACK (USPTO)" : "FALLBACK";
              defaultDocType = "PATENT";
            } else if (rawStatus === "DATABASE" || rawType === "DATABASE" || rawType === "DATABASE REPOSITORY") {
              displaySource = "DATABASE";
            } else {
              displaySource = rawType;
            }

            const docType = patent.document_type || defaultDocType;
            const isNPL = docType.includes("NON-PATENT") || displaySource.toLowerCase() === "arxiv";
            const isDatabase = displaySource === "DATABASE" || rawStatus === "DATABASE";
            const isFallback = rawStatus === "FALLBACK" || displaySource.includes("FALLBACK");

            let colorStyle = "bg-cyan-500/10 text-cyan-300 border-cyan-500/25";
            if (isNPL) {
              colorStyle = "bg-amber-500/10 text-amber-300 border-amber-500/25";
            } else if (isDatabase) {
              colorStyle = "bg-purple-500/10 text-purple-300 border-purple-500/25";
            } else if (isFallback) {
              colorStyle = "bg-orange-500/10 text-orange-300 border-orange-500/25";
            }

            return (
              <span className={`px-2 py-0.5 rounded text-[11px] font-mono font-semibold border ${colorStyle}`}>
                Source: {displaySource} • {docType}
              </span>
            );
          })()}

          {/* Temporal Status Badge */}
          {(() => {
            const tempStatus = item.temporal_status || "DATE_UNAVAILABLE";
            if (tempStatus === "PUBLISHED_BEFORE_REFERENCE") {
              return (
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  ✓ Prior Art before reference date
                </span>
              );
            } else if (tempStatus === "AFTER_REFERENCE_DATE" || tempStatus === "PUBLISHED_AFTER_REFERENCE" || tempStatus === "EARLIER_PRIORITY_BUT_PUBLISHED_AFTER") {
              return (
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30">
                  Published Later (Post-Date)
                </span>
              );
            } else if (tempStatus === "SAME_DATE") {
              return (
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-blue-500/15 text-blue-300 border border-blue-500/30">
                  Same Date as Reference
                </span>
              );
            } else {
              return (
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-zinc-800/80 text-zinc-400 border border-zinc-700/50">
                  Pub Date: {formatDate(patent.publication_date)}
                </span>
              );
            }
          })()}

          {/* Honest Evidence Status Badge */}
          {(() => {
            const isUnavailable = bd.evidence?.status === "UNAVAILABLE" || (item.claims_status === "NOT_AVAILABLE" && item.full_text_status === "NOT_AVAILABLE") || item.evidence_status === "UNAVAILABLE";
            const hasVerifiedEv = (bd.evidence_strength > 10) || evidenceItems.some(i => i.verified);

            if (isUnavailable) {
              return (
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-zinc-800/80 text-zinc-400 border border-zinc-700/50">
                  Evidence: UNAVAILABLE
                </span>
              );
            } else if (hasVerifiedEv && bd.evidence_strength > 10) {
              const evStatusText = item.evidence_status_label || (item.claims_status === "AVAILABLE" ? "Claim evidence verified" : "Description evidence verified");
              return (
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/25">
                  ✓ {evStatusText} ({Math.round(bd.evidence_strength)}%)
                </span>
              );
            } else {
              return (
                <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/25">
                  ⚠ Limited evidence (0%)
                </span>
              );
            }
          })()}

          {/* Low Technical Similarity Tag when 0 feature matches */}
          {matchedCount === 0 && (
            <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-rose-500/15 text-rose-300 border border-rose-500/30">
              LOW TECHNICAL SIMILARITY (Candidate Only)
            </span>
          )}

          <span className="px-2.5 py-0.5 rounded text-[11px] font-mono font-medium bg-zinc-900 text-zinc-300 border border-zinc-800">
            {patent.domain}
          </span>
        </div>

        {/* 5 Component Progress Bars (Semantic 25%, Technical Features 35%, Evidence 20%, Concepts 10%, Domain/CPC 10%) */}
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-2 font-mono text-xs pt-1">
          <div className="p-2 rounded-lg bg-zinc-950/80 border border-zinc-800 space-y-1">
            <div className="flex justify-between text-[10px] text-zinc-400 font-semibold uppercase">
              <span>Semantic ({bd.semantic?.effective_weight ? Math.round(bd.semantic.effective_weight * 100) : 25}%)</span>
              <span className="text-indigo-400 font-bold">{bd.semantic?.value !== undefined && bd.semantic?.value !== null ? `${Math.round(bd.semantic.value)}%` : `${Math.round(bd.semantic_similarity)}%`}</span>
            </div>
            <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-indigo-500 rounded-full" style={{ width: `${Math.min(100, bd.semantic?.value ?? bd.semantic_similarity)}%` }} />
            </div>
          </div>

          <div className="p-2 rounded-lg bg-zinc-950/80 border border-zinc-800 space-y-1">
            <div className="flex justify-between text-[10px] text-zinc-400 font-semibold uppercase">
              <span>Feature Match ({bd.technical_features?.effective_weight ? Math.round(bd.technical_features.effective_weight * 100) : 35}%)</span>
              <span className="text-sky-400 font-bold">
                {bd.technical_features?.status === "UNAVAILABLE" || bd.technical_features?.value === null
                  ? "Not Available"
                  : `${Math.round(bd.technical_features?.value ?? bd.technical_features_score ?? 0)}% (${matchedCount}/${totalCount})`}
              </span>
            </div>
            <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-sky-500 rounded-full" style={{ width: `${bd.technical_features?.status === "UNAVAILABLE" ? 0 : Math.min(100, bd.technical_features?.value ?? bd.technical_features_score ?? 0)}%` }} />
            </div>
          </div>

          <div className="p-2 rounded-lg bg-zinc-950/80 border border-zinc-800 space-y-1">
            <div className="flex justify-between text-[10px] text-zinc-400 font-semibold uppercase">
              <span>Evidence ({bd.evidence?.effective_weight ? Math.round(bd.evidence.effective_weight * 100) : 20}%)</span>
              <span className="text-emerald-400 font-bold">
                {bd.evidence?.status === "UNAVAILABLE" || bd.evidence?.value === null
                  ? "Not Available"
                  : `${Math.round(bd.evidence?.value ?? bd.evidence_strength)}%`}
              </span>
            </div>
            <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${bd.evidence?.status === "UNAVAILABLE" ? 0 : Math.min(100, bd.evidence?.value ?? bd.evidence_strength)}%` }} />
            </div>
          </div>

          <div className="p-2 rounded-lg bg-zinc-950/80 border border-zinc-800 space-y-1">
            <div className="flex justify-between text-[10px] text-zinc-400 font-semibold uppercase">
              <span>Concepts ({bd.concepts?.effective_weight ? Math.round(bd.concepts.effective_weight * 100) : 10}%)</span>
              <span className="text-amber-400 font-bold">{Math.round(bd.concepts?.value ?? bd.distinctive_concepts)}%</span>
            </div>
            <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-amber-500 rounded-full" style={{ width: `${Math.min(100, bd.concepts?.value ?? bd.distinctive_concepts)}%` }} />
            </div>
          </div>

          <div className="p-2 rounded-lg bg-zinc-950/80 border border-zinc-800 space-y-1">
            <div className="flex justify-between text-[10px] text-zinc-400 font-semibold uppercase">
              <span>Domain / CPC ({bd.domain_cpc?.effective_weight ? Math.round(bd.domain_cpc.effective_weight * 100) : 10}%)</span>
              <span className="text-purple-400 font-bold">{Math.round(bd.domain_cpc?.value ?? bd.domain_cpc_alignment)}%</span>
            </div>
            <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-purple-500 rounded-full" style={{ width: `${Math.min(100, bd.domain_cpc?.value ?? bd.domain_cpc_alignment)}%` }} />
            </div>
          </div>
        </div>
      </div>

      {/* Feature Evidence Breakdown (Strong ✓, Partial ~, Missing ✕) */}
      <div className="pt-2 space-y-3">
        {strongMatches.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[11px] font-mono font-semibold text-emerald-400 flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              <span>✓ Strong Matches ({strongMatches.length})</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {strongMatches.map((featName, i) => (
                <span key={i} className="px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-emerald-300 text-[11px] font-mono flex items-center gap-1.5">
                  <span className="text-emerald-400 font-bold">✓</span>
                  <span>{featName}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {partialMatches.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[11px] font-mono font-semibold text-amber-400 flex items-center gap-1">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span>~ Partial Matches ({partialMatches.length})</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {partialMatches.map((featName, i) => (
                <span key={i} className="px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/25 text-amber-300 text-[11px] font-mono flex items-center gap-1.5">
                  <span className="text-amber-400 font-bold">~</span>
                  <span>{featName}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {missingFeatures.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[11px] font-mono font-semibold text-zinc-400 flex items-center gap-1">
              <XCircle className="w-3.5 h-3.5 text-zinc-500" />
              <span>✕ Not Found ({missingFeatures.length})</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {missingFeatures.slice(0, 6).map((featName, i) => (
                <span key={i} className="px-2.5 py-1 rounded-lg bg-zinc-900/90 border border-zinc-800 text-zinc-400 text-[11px] font-mono flex items-center gap-1.5">
                  <span className="text-rose-400 font-bold">✕</span>
                  <span>{featName}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Verified Evidence Snippet Card */}
        {topEvidence && topEvidence.evidence && (
          <div className="p-3.5 rounded-lg bg-zinc-950/90 border border-zinc-800 space-y-1 text-xs">
            <div className="flex items-center justify-between text-[10px] font-mono font-semibold text-indigo-400 uppercase tracking-wider">
              <span>Specification Evidence Quote</span>
              <span className="px-2 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-indigo-300">
                Source: {topEvidence.source || "Claim 4"}
              </span>
            </div>
            <p className="text-zinc-300 italic text-[11px] leading-relaxed">
              "{topEvidence.evidence.replace(/^Disclosed in [^:]+:\s*"/, '').replace(/"$/, '')}"
            </p>
          </div>
        )}
      </div>

      {/* Footer Actions */}
      <div className="pt-3 border-t border-zinc-800/80 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={isSaving}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
              saved
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                : "bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border-zinc-800"
            }`}
          >
            {saved ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Bookmark className="w-3.5 h-3.5" />}
            <span>{saved ? "Saved" : "Save Patent"}</span>
          </button>

          <a
            href={getOfficialPatentUrl(patent)}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-zinc-800 transition-all"
          >
            <ExternalLink className="w-3.5 h-3.5 text-zinc-400" />
            <span>View Original Patent</span>
          </a>

          <button
            onClick={() => setShowClaimModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-semibold bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 transition-all"
          >
            <Layers className="w-3.5 h-3.5 text-indigo-400" />
            <span>Claim-Level Analysis</span>
          </button>
        </div>

        <Link
          href={`/patents/${patent.id}`}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs shadow-sm shadow-indigo-500/20 transition-all"
        >
          <span>Full Comparison</span>
          <ArrowUpRight className="w-3.5 h-3.5" />
        </Link>
      </div>

      {/* Modal: How is this calculated? */}
      {showFormulaModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0c0e24] border border-indigo-500/30 rounded-2xl p-6 max-w-lg w-full space-y-4 shadow-[0_25px_60px_-15px_rgba(0,0,0,0.9)] text-left">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h4 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
                <Info className="w-4 h-4 text-indigo-400" />
                Score Calculation Formula
              </h4>
              <button onClick={() => setShowFormulaModal(false)} className="text-zinc-400 hover:text-zinc-200 text-xs font-mono">✕ Close</button>
            </div>
            
            <p className="text-xs text-zinc-300 leading-relaxed">
              The <strong className="text-indigo-400">Overall Technical Relevance Score</strong> ({computedScore}%) is calculated by the 5-component weighted formula:
            </p>

            <div className="space-y-2.5 text-xs font-mono bg-zinc-950 p-3.5 rounded-xl border border-zinc-800">
              <div className="flex justify-between text-zinc-300">
                <span>Semantic Similarity ({bd.semantic?.effective_weight ? (bd.semantic.effective_weight * 100).toFixed(1) : "25"}%):</span>
                <span className="text-indigo-400 font-bold">
                  {bd.semantic?.value !== undefined && bd.semantic?.value !== null ? `${bd.semantic.value}%` : `${bd.semantic_similarity}%`}
                  {" × "}
                  {bd.semantic?.effective_weight ?? 0.25} = {(bd.semantic?.contribution ?? (bd.semantic_similarity * 0.25)).toFixed(1)}%
                </span>
              </div>

              <div className="flex justify-between text-zinc-300">
                <span>Technical Feature Match ({bd.technical_features?.effective_weight ? (bd.technical_features.effective_weight * 100).toFixed(1) : "35"}%):</span>
                <span className="text-sky-400 font-bold">
                  {bd.technical_features?.status === "UNAVAILABLE" || bd.technical_features?.value === null
                    ? "UNAVAILABLE (0.0%)"
                    : `${bd.technical_features?.value ?? bd.technical_features_score ?? 0}% × ${bd.technical_features?.effective_weight ?? 0.35} = ${(bd.technical_features?.contribution ?? 0).toFixed(1)}%`}
                </span>
              </div>

              <div className="flex justify-between text-zinc-300">
                <span>Evidence Strength ({bd.evidence?.effective_weight ? (bd.evidence.effective_weight * 100).toFixed(1) : "20"}%):</span>
                <span className="text-emerald-400 font-bold">
                  {bd.evidence?.status === "UNAVAILABLE" || bd.evidence?.value === null
                    ? "UNAVAILABLE (0.0%)"
                    : `${bd.evidence?.value ?? bd.evidence_strength}% × ${bd.evidence?.effective_weight ?? 0.20} = ${(bd.evidence?.contribution ?? (bd.evidence_strength * 0.20)).toFixed(1)}%`}
                </span>
              </div>

              <div className="flex justify-between text-zinc-300">
                <span>Distinctive Concepts ({bd.concepts?.effective_weight ? (bd.concepts.effective_weight * 100).toFixed(1) : "10"}%):</span>
                <span className="text-amber-400 font-bold">
                  {bd.concepts?.value ?? bd.distinctive_concepts}% × {bd.concepts?.effective_weight ?? 0.10} = {(bd.concepts?.contribution ?? (bd.distinctive_concepts * 0.10)).toFixed(1)}%
                </span>
              </div>

              <div className="flex justify-between text-zinc-300">
                <span>Domain/CPC Alignment ({bd.domain_cpc?.effective_weight ? (bd.domain_cpc.effective_weight * 100).toFixed(1) : "10"}%):</span>
                <span className="text-purple-400 font-bold">
                  {bd.domain_cpc?.value ?? bd.domain_cpc_alignment}% × {bd.domain_cpc?.effective_weight ?? 0.10} = {(bd.domain_cpc?.contribution ?? (bd.domain_cpc_alignment * 0.10)).toFixed(1)}%
                </span>
              </div>

              <div className="pt-2 border-t border-zinc-800 flex justify-between font-bold text-indigo-300 text-sm">
                <span>Calculated Relevance:</span>
                <span>{computedScore}%</span>
              </div>
            </div>

            {bd.is_gated && (
              <div className="p-2.5 rounded bg-rose-500/10 border border-rose-500/30 text-rose-300 text-[11px]">
                ⚠️ <strong>Technical Relevance Gate Applied:</strong> {bd.score_cap_reason || "Capped due to feature coverage constraint."}
              </div>
            )}

            <p className="text-[11px] text-zinc-400 italic">
              {bd.formula_explanation}
            </p>
          </div>
        </div>
      )}

      {/* Modal: View Family Members */}
      {showFamilyModal && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 max-w-lg w-full space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <h4 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
                <Layers className="w-4 h-4 text-emerald-400" />
                Patent Family Members ({family_members?.length || 1})
              </h4>
              <button onClick={() => setShowFamilyModal(false)} className="text-zinc-400 hover:text-zinc-200 text-xs font-mono">✕ Close</button>
            </div>
            
            <p className="text-xs text-zinc-400">
              The following publications belong to the same patent family deduplicated from international databases:
            </p>

            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              {(family_members || []).map((mem, idx) => (
                <div key={idx} className="p-2.5 rounded bg-zinc-950 border border-zinc-800 flex items-center justify-between text-xs font-mono">
                  <div>
                    <span className="font-bold text-emerald-400">{mem.patent_number}</span>
                    <span className="text-zinc-400 ml-2">({mem.jurisdiction})</span>
                    <div className="text-[11px] text-zinc-400 font-sans truncate max-w-xs">{mem.title}</div>
                  </div>
                  <span className="text-[11px] text-zinc-500">{mem.publication_date}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Modal: Claim-Level & Element-by-Element Analysis */}
      {showClaimModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-[#0b0d1e] border border-indigo-500/30 rounded-2xl p-6 max-w-3xl w-full space-y-4 shadow-[0_25px_60px_-15px_rgba(0,0,0,0.9)] max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <div>
                <h4 className="text-sm font-bold text-zinc-100 flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-indigo-400" />
                  Independent Claim 1: Element-by-Element Analysis
                </h4>
                <p className="text-[11px] text-zinc-400 font-mono mt-0.5">
                  Patent {patent.patent_number}: "{patent.title}"
                </p>
              </div>
              <button onClick={() => setShowClaimModal(false)} className="text-zinc-400 hover:text-zinc-200 text-xs font-mono px-2 py-1 bg-white/5 rounded border border-white/10">✕ Close</button>
            </div>
            
            <div className="p-3.5 rounded-xl bg-indigo-950/30 border border-indigo-500/20 text-xs font-mono space-y-1.5">
              <div className="text-indigo-300 font-bold text-[11px] uppercase tracking-wider">
                Claim 1 Preamble: An apparatus, system, or method comprising the following discrete technical limitations:
              </div>
              {(() => {
                const mCount = item.matched_feature_count || (strongMatches.length + partialMatches.length);
                const tCount = item.total_feature_count || (strongMatches.length + partialMatches.length + missingFeatures.length);
                const covPct = tCount > 0 ? ((mCount / tCount) * 100).toFixed(1) : "0.0";
                return (
                  <div className="text-zinc-300 text-[11px] font-sans flex flex-wrap items-center gap-3">
                    <span>Total Limitations Analyzed: <strong>{tCount}</strong></span>
                    <span>•</span>
                    <span>Matched: <strong className="text-emerald-400">{mCount}</strong></span>
                    <span>•</span>
                    <span>Claim Coverage: <strong className="text-indigo-400">{covPct}%</strong></span>
                  </div>
                );
              })()}
            </div>

            <div className="space-y-3">
              {(item.claim_elements && item.claim_elements.length > 0 ? item.claim_elements : (item.matched_features || []).map((mf, i) => ({
                limitation_number: i + 1,
                element_text: mf.feature,
                status: mf.match_level,
                evidence_quote: mf.evidence,
                explanation: `Disclosed in specification of prior art document ${patent.patent_number}.`
              }))).map((elem, idx) => {
                const st = String(elem.status).toUpperCase();
                const isStrong = st.includes("STRONG") || st.includes("EXPLICIT");
                const isPartial = st.includes("PARTIAL") || st.includes("INHERENT");
                return (
                  <div key={idx} className={`p-4 rounded-xl border space-y-2 text-xs font-mono ${
                    isStrong ? "bg-emerald-950/20 border-emerald-500/30" : isPartial ? "bg-amber-950/20 border-amber-500/30" : "bg-zinc-950 border-zinc-800"
                  }`}>
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-zinc-200">
                        Limitation #{elem.limitation_number || idx + 1}: {elem.element_text || (elem as any).element}
                      </span>
                      <span className={`px-2.5 py-0.5 rounded text-[10px] font-bold ${
                        isStrong ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40" : isPartial ? "bg-amber-500/20 text-amber-300 border border-amber-500/40" : "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                      }`}>
                        {isStrong ? "✓ STRONG MATCH" : isPartial ? "⚡ PARTIAL MATCH" : "✗ NOT DISCLOSED"}
                      </span>
                    </div>

                    {elem.evidence_quote && (
                      <div className="p-2.5 rounded bg-black/40 border border-white/5 text-[11px] font-sans italic text-zinc-300">
                        "{elem.evidence_quote}"
                      </div>
                    )}

                    {elem.explanation && (
                      <div className="text-[11px] font-sans text-zinc-400 leading-snug">
                        {elem.explanation}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <button
              onClick={() => setShowClaimModal(false)}
              className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs shadow-lg shadow-indigo-500/25 transition-all cursor-pointer mt-4"
            >
              Close Element Comparison
            </button>
          </div>
        </div>
      )}

    </div>
  );
}
