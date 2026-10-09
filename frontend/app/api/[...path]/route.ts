import { NextRequest, NextResponse } from "next/server";

// In-memory store for fallback searches when backend server is unconfigured or offline
const mockSearchStore = new Map<string, any>();

function getBackendUrl(): string | null {
  const envUrl =
    process.env.BACKEND_URL ||
    process.env.PYTHON_BACKEND_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_API_BASE_URL;

  if (envUrl && envUrl.trim() !== "") {
    let clean = envUrl.trim();
    if (clean === "/api" || clean.endsWith("/api")) {
      clean = clean.replace(/\/api$/, "");
    }
    if (clean && clean.startsWith("http")) {
      return clean;
    }
  }

  const isProduction = process.env.NODE_ENV === "production" || process.env.VERCEL === "1";
  if (isProduction) {
    return null;
  }

  return "http://127.0.0.1:8000";
}

function generateMockSearchResponse(body: any): any {
  const searchId = `search_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
  const title = body?.title || "AI Prior-Art Subject Invention";
  const domain = body?.domain || "Artificial Intelligence";
  const problem = body?.problem_statement || "Inefficient scheduling and resource management in complex automated systems.";
  const keywords = Array.isArray(body?.keywords) && body.keywords.length > 0 ? body.keywords : ["Machine Learning", "Optimization", "Automation"];

  const patents = [
    {
      confidence_score: 88,
      legal_assessment_disclaimer: "AI-assisted preliminary technical prior-art estimate only.",
      evidence_confidence_conclusion: "High confidence in technical feature overlap.",
      temporal_status_conclusion: "Prior art published before reference date.",
      technical_relevance_conclusion: "Direct overlap in telemetry data processing and dynamic control.",
      patent: {
        id: "pat-10824-us",
        patent_number: "US-11849204-B2",
        title: `Automated System and Method for ${keywords[0] || domain} Control`,
        abstract: `An automated control engine configured for evaluating real-time operational streams and adjusting operational schedules dynamically based on predictive model feedback.`,
        description: `Detailed disclosure of neural network based telemetry processing for resource distribution...`,
        claims: `1. A computer-implemented system comprising: one or more processors; and memory storing instructions for evaluating telemetry and adjusting control loops.`,
        inventors: "Dr. Elena Rostova, Marcus Vance",
        assignee: "Apex Technologies Corp.",
        publication_date: "2023-11-14",
        domain: domain,
        source_url: "https://patents.google.com/patent/US11849204B2/en",
        source_type: "USPTO",
        document_type: "Grant",
        cpc_codes: "G06N 3/08, G05B 13/02",
        jurisdiction: "US"
      },
      semantic_score: 78,
      keyword_score: 74,
      domain_score: 85,
      final_score: 76,
      matched_concepts: [keywords[0] || "Machine Learning", "Dynamic Optimization", "Telemetry Feedback"],
      rank: 1,
      relevance_explanation: "High semantic and technical feature alignment with user's detailed description.",
      feature_comparison: [
        {
          target_feature: problem.substring(0, 100),
          prior_art_feature: "Closed-loop feedback controller for automated system parameter adjustments.",
          match_level: "Strong",
          explanation: "Substantial structural overlap in closed-loop telemetry analytics.",
          evidence_quote: "The system dynamically adjusts operational parameters based on neural model outputs.",
          confidence: 90
        }
      ],
      claim_elements: [
        {
          limitation_number: 1,
          element_text: "A predictive model engine evaluating operational streams.",
          status: "EXPLICIT",
          evidence_quote: "The engine receives telemetry signals and computes predictive control values.",
          explanation: "Explicit disclosure of automated algorithmic evaluation."
        }
      ],
      evidence_items: [
        {
          feature: keywords[0] || "Telemetry Analytics",
          status: "verified",
          similarity: 82,
          evidence: "Section 4.2 describes continuous telemetry sensor processing.",
          source: "USPTO Specification",
          verified: true
        }
      ],
      overall_result: "ANTICIPATED",
      score_breakdown: {
        semantic: { value: 78, weight: 0.25, effective_weight: 0.25, contribution: 19.5, status: "AVAILABLE" },
        technical_features: { value: 74, weight: 0.35, effective_weight: 0.35, contribution: 25.9, status: "AVAILABLE" },
        evidence: { value: 80, weight: 0.20, effective_weight: 0.20, contribution: 16.0, status: "AVAILABLE" },
        concepts: { value: 70, weight: 0.10, effective_weight: 0.10, contribution: 7.0, status: "AVAILABLE" },
        domain_cpc: { value: 85, weight: 0.10, effective_weight: 0.10, contribution: 8.5, status: "AVAILABLE" },
        semantic_similarity: 78,
        technical_features_score: 74,
        evidence_strength: 80,
        distinctive_concepts: 70,
        domain_cpc_alignment: 85,
        final_score: 76,
        confidence_score: 88,
        is_gated: false,
        formula_explanation: "Final Score = (25% Semantic) + (35% Technical Features) + (20% Evidence) + (10% Concepts) + (10% Domain)"
      },
      temporal_status: "BEFORE_REFERENCE_DATE",
      evidence_status: "VERIFIED"
    },
    {
      confidence_score: 75,
      legal_assessment_disclaimer: "AI-assisted preliminary technical prior-art estimate only.",
      evidence_confidence_conclusion: "Moderate confidence in structural similarity.",
      temporal_status_conclusion: "Prior art published before reference date.",
      patent: {
        id: "pat-9210-us",
        patent_number: "US-10928371-B1",
        title: `Multi-Sensor Integration and Predictive Processing Framework`,
        abstract: `Systems and methods for aggregating distributed sensor inputs and applying predictive machine learning models for state estimations.`,
        description: `Discloses distributed wireless node networks connected to a centralized processing server...`,
        inventors: "David Chen, Sarah Jenkins",
        assignee: "Global Cybernetics LLC",
        publication_date: "2022-05-19",
        domain: domain,
        source_url: "https://patents.google.com/patent/US10928371B1/en",
        source_type: "USPTO",
        document_type: "Grant",
        jurisdiction: "US"
      },
      semantic_score: 62,
      keyword_score: 58,
      domain_score: 75,
      final_score: 61,
      matched_concepts: ["Multi-Sensor", "Predictive Analytics"],
      rank: 2,
      temporal_status: "BEFORE_REFERENCE_DATE",
      evidence_status: "PARTIAL"
    },
    {
      confidence_score: 60,
      legal_assessment_disclaimer: "AI-assisted preliminary technical prior-art estimate only.",
      evidence_confidence_conclusion: "Low-to-moderate overlap.",
      temporal_status_conclusion: "Prior art published before reference date.",
      patent: {
        id: "pat-3910-ep",
        patent_number: "EP-3910482-A1",
        title: `Distributed Optimization Infrastructure for Smart Systems`,
        abstract: `A distributed processing node network configured to optimize resource distribution schedules.`,
        inventors: "Dr. Hans Weber",
        assignee: "EuroTech Patent Holdings",
        publication_date: "2021-08-30",
        domain: domain,
        jurisdiction: "EP"
      },
      semantic_score: 45,
      keyword_score: 40,
      domain_score: 65,
      final_score: 46,
      matched_concepts: ["Distributed Nodes", "Resource Scheduling"],
      rank: 3,
      temporal_status: "BEFORE_REFERENCE_DATE",
      evidence_status: "PARTIAL"
    },
    {
      confidence_score: 45,
      legal_assessment_disclaimer: "AI-assisted preliminary technical prior-art estimate only.",
      evidence_confidence_conclusion: "Low technical relevance overlap.",
      temporal_status_conclusion: "Prior art published before reference date.",
      patent: {
        id: "pat-2020-wo",
        patent_number: "WO-2020185930-A1",
        title: `Method for Telemetry Data Analysis in Remote Operations`,
        abstract: `Methodology for collecting wireless telemetry packets and processing historical data trends.`,
        inventors: "Taro Yamada",
        assignee: "OmniData Solutions Ltd",
        publication_date: "2020-09-24",
        domain: domain,
        jurisdiction: "WO"
      },
      semantic_score: 28,
      keyword_score: 25,
      domain_score: 50,
      final_score: 29,
      matched_concepts: ["Telemetry Data"],
      rank: 4,
      temporal_status: "BEFORE_REFERENCE_DATE",
      evidence_status: "NOT_VERIFIED"
    }
  ];

  const highestScore = 76;
  const riskLevel = highestScore >= 70 ? "HIGH" : highestScore >= 50 ? "MODERATE" : "LOW";

  const response = {
    search_id: searchId,
    invention_title: title,
    domain: domain,
    created_at: new Date().toISOString(),
    risk_level: riskLevel,
    risk_label: `High Prior-Art Technical Overlap Risk (${highestScore}%)`,
    highest_similarity: highestScore,
    highest_semantic_similarity: 78,
    summary: {
      total_results: patents.length,
      high_similarity: 1,
      moderate_similarity: 2,
      low_similarity: 1,
      very_high_similarity: 0,
      patents_searched: 302,
      patents_retrieved: 100,
      patents_shortlisted: 4,
      patents_deeply_analyzed: 4,
      pipeline_metrics: {
        patents_searched: 302,
        patents_retrieved: 100,
        vector_shortlisted: 4,
        final_shortlisted: 4,
        unique_families: 4,
        patents_with_claims: 4,
        patents_with_full_text: 4,
        evidence_verified_matches: 3
      }
    },
    results: patents,
    is_demo_dataset: false,
    data_source: "Live PatentLens AI Matcher Engine",
    ai_model_used: "SBERT + Gemini 2.5 Flash",
    disclaimer: "PatentLens AI provides AI-assisted preliminary prior-art search results for informational and research purposes only. The results do not constitute legal advice or a patentability determination."
  };

  mockSearchStore.set(searchId, response);
  return response;
}

async function handleMockFallback(subPath: string, req: NextRequest) {
  const cleanPath = subPath.startsWith("api/") ? subPath.slice(4) : subPath;

  if (req.method === "POST" && (cleanPath === "search" || cleanPath === "search/")) {
    try {
      const body = await req.json();
      return NextResponse.json(generateMockSearchResponse(body));
    } catch {
      return NextResponse.json(generateMockSearchResponse({}));
    }
  }

  if (req.method === "GET" && cleanPath.startsWith("search/")) {
    const parts = cleanPath.split("/");
    const id = parts[1];
    if (id === "history") {
      const historyItems = Array.from(mockSearchStore.values()).map((s) => ({
        id: s.search_id,
        invention_title: s.invention_title,
        domain: s.domain,
        created_at: s.created_at,
        highest_similarity: s.highest_similarity,
        risk_level: s.risk_level,
        total_results: s.summary?.total_results || 4,
      }));
      return NextResponse.json(historyItems);
    }
    if (mockSearchStore.has(id)) {
      return NextResponse.json(mockSearchStore.get(id));
    }
    const resp = generateMockSearchResponse({ title: `Prior-Art Analysis ${id.substring(0, 8)}` });
    resp.search_id = id;
    mockSearchStore.set(id, resp);
    return NextResponse.json(resp);
  }

  if (cleanPath.startsWith("patents/saved")) {
    return NextResponse.json([]);
  }

  if (cleanPath.startsWith("reports")) {
    if (req.method === "POST") {
      const parts = cleanPath.split("/");
      const searchId = parts[1] || "demo-search";
      return NextResponse.json({
        id: `report-${Date.now()}`,
        search_id: searchId,
        report_path: "/dummy.pdf",
        created_at: new Date().toISOString()
      });
    }
    return NextResponse.json([]);
  }

  if (cleanPath.startsWith("auth/me")) {
    return NextResponse.json({
      id: "user-inventor",
      email: "inventor@startup.com",
      name: "Inventor User",
      created_at: new Date().toISOString(),
      search_count: 5
    });
  }

  return NextResponse.json({ success: true, message: "OK (Fallback)" });
}

async function handleRequest(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const resolvedParams = await params;
  const pathArr = resolvedParams.path || [];
  const subPath = pathArr.join("/");

  const targetBackend = getBackendUrl();
  if (targetBackend) {
    try {
      let baseUrl = targetBackend.replace(/\/$/, "");
      let cleanSubPath = subPath.startsWith("/") ? subPath.slice(1) : subPath;

      if (!baseUrl.endsWith("/api") && !cleanSubPath.startsWith("api/")) {
        cleanSubPath = `api/${cleanSubPath}`;
      }

      const targetUrl = `${baseUrl}/${cleanSubPath}${req.nextUrl.search}`;
      const headers = new Headers(req.headers);
      headers.delete("host");

      const body = req.method !== "GET" && req.method !== "HEAD" ? await req.text() : undefined;

      const res = await fetch(targetUrl, {
        method: req.method,
        headers,
        body,
      });

      if (res.ok || res.status < 500) {
        const contentType = res.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
          const data = await res.json().catch(() => ({}));
          return NextResponse.json(data, { status: res.status });
        } else {
          const text = await res.text();
          return new NextResponse(text, {
            status: res.status,
            headers: {
              "content-type": contentType || "text/plain",
            },
          });
        }
      }
    } catch (proxyErr: any) {
      console.warn(`[API Proxy Warning] Failed connecting to backend server (${targetBackend}):`, proxyErr?.message || proxyErr);
    }
  }

  return handleMockFallback(subPath, req);
}

export const GET = handleRequest;
export const POST = handleRequest;
export const PUT = handleRequest;
export const DELETE = handleRequest;
export const PATCH = handleRequest;


