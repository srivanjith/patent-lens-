"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Sidebar from "@/components/Sidebar";
import RiskBadge from "@/components/RiskBadge";
import {
  Search,
  Bookmark,
  FileText,
  TrendingUp,
  ArrowUpRight,
  PlusCircle,
  History,
  Sparkles,
  ChevronRight,
  ArrowRight,
  ShieldAlert,
  ShieldCheck,
  Zap
} from "lucide-react";
import { api } from "@/services/api";
import { SearchHistoryItem, SavedPatent, Report, User } from "@/types";
import { formatDate } from "@/lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell
} from "recharts";
import { useRouter } from "next/navigation";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [history, setHistory] = useState<SearchHistoryItem[]>([]);
  const [saved, setSaved] = useState<SavedPatent[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadDashboardData() {
      try {
        const u = await api.getMe();
        setUser(u);
        const [h, s, r] = await Promise.all([
          api.getSearchHistory(),
          api.getSavedPatents(),
          api.getReports(),
        ]);
        setHistory(h);
        setSaved(s);
        setReports(r);
      } catch (err) {
        console.error("Dashboard error:", err);
        router.push("/login");
      } finally {
        setLoading(false);
      }
    }
    loadDashboardData();
  }, [router]);

  const totalSearches = history.length;
  const savedCount = saved.length;
  const reportsCount = reports.length;
  const highestSim = history.length > 0
    ? Math.max(...history.map((item) => item.highest_similarity))
    : 0;

  const chartData = history.slice(0, 5).reverse().map((h) => ({
    title: h.invention_title.length > 12 ? h.invention_title.substring(0, 12) + "..." : h.invention_title,
    score: h.highest_similarity,
  }));

  // Fallback demo data if history is empty to match user mockup closely
  const displayHistory = history.length > 0 ? history : [
    {
      id: "demo-1",
      invention_title: "Three-Terminal Semiconductor Signal Amplifying Device",
      domain: "Electronics",
      created_at: "2026-09-09T12:00:00Z",
      highest_similarity: 25.0,
      risk_level: "LOW",
      total_results: 10
    },
    {
      id: "demo-2",
      invention_title: "Intermittent Motion Mechanism",
      domain: "Other",
      created_at: "2026-09-09T11:00:00Z",
      highest_similarity: 18.1,
      risk_level: "LOW",
      total_results: 8
    },
    {
      id: "demo-3",
      invention_title: "Adaptive Safety Monitoring System for Contactless Vehicle",
      domain: "Electronics",
      created_at: "2026-09-07T10:00:00Z",
      highest_similarity: 30.0,
      risk_level: "LOW",
      total_results: 12
    }
  ];

  const displayChartData = chartData.length > 0 ? chartData : [
    { title: "Adaptive Safety...", score: 30 },
    { title: "Intermittent Motion...", score: 18.1 },
    { title: "Three-Terminal...", score: 25 }
  ];

  return (
    <div className="min-h-screen bg-[#07091e] text-white flex relative overflow-hidden font-sans selection:bg-purple-500 selection:text-white">
      
      {/* Radiant Gradient / Creative Mesh Background */}
      <div className="absolute inset-0 pointer-events-none z-0">
        {/* Top Left Indigo-Purple Aura */}
        <div className="absolute -top-24 -left-24 w-[600px] h-[600px] rounded-full bg-gradient-to-tr from-indigo-600/40 via-purple-600/30 to-pink-500/20 blur-[120px]" />
        
        {/* Right Center Blue-Cyan Glow */}
        <div className="absolute top-1/4 -right-24 w-[700px] h-[700px] rounded-full bg-gradient-to-bl from-cyan-400/30 via-indigo-600/20 to-purple-900/30 blur-[140px]" />
        
        {/* Bottom Left Peach-Pink Highlight */}
        <div className="absolute -bottom-24 left-1/3 w-[650px] h-[650px] rounded-full bg-gradient-to-tr from-pink-500/25 via-purple-600/20 to-indigo-800/20 blur-[130px]" />

        {/* Ambient Silk Wave Line Overlays */}
        <svg className="w-full h-full opacity-20" xmlns="http://www.w3.org/2000/svg">
          <path d="M -200 400 Q 300 200 800 500 T 1800 400" fill="none" stroke="url(#gradient-line-1)" strokeWidth="2" />
          <path d="M -200 500 Q 300 300 800 600 T 1800 500" fill="none" stroke="url(#gradient-line-2)" strokeWidth="1.5" />
          <defs>
            <linearGradient id="gradient-line-1" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#a855f7" />
              <stop offset="100%" stopColor="#38bdf8" />
            </linearGradient>
            <linearGradient id="gradient-line-2" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#ec4899" />
              <stop offset="100%" stopColor="#818cf8" />
            </linearGradient>
          </defs>
        </svg>
      </div>

      <Sidebar />

      <main className="flex-1 p-6 sm:p-10 overflow-y-auto z-10">
        <div className="max-w-7xl mx-auto space-y-8">
          
          {/* Header & Welcome Banner */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
            <div>
              <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight flex items-center gap-2">
                Welcome back, <span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-300 via-pink-200 to-amber-200">{user?.name || (user?.email ? user.email.split("@")[0] : "User")}</span> 👋
              </h1>
              <p className="text-xs sm:text-sm text-purple-200/80 mt-1 font-medium">
                Turn ideas into insights with AI.
              </p>
            </div>
            
            <Link
              href="/search"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-500 hover:scale-105 active:scale-95 text-white font-bold text-xs shadow-lg shadow-indigo-500/30 border border-white/20 transition-all self-start sm:self-auto"
            >
              <PlusCircle className="w-4 h-4 text-white" />
              <span>Start New Search</span>
            </Link>
          </div>

          {/* Top 4 Glass Stat Cards Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            
            {/* Stat 1: Total Searches */}
            <div className="p-6 rounded-2xl bg-white/[0.08] backdrop-blur-2xl border border-white/20 shadow-xl hover:bg-white/[0.12] hover:border-white/30 transition-all group">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-purple-200/80 tracking-wide uppercase">Total Searches</span>
                <div className="w-10 h-10 rounded-xl bg-purple-500/20 border border-purple-400/30 flex items-center justify-center text-purple-300 group-hover:scale-110 transition-transform">
                  <Search className="w-5 h-5" />
                </div>
              </div>
              <div className="text-3xl font-black font-mono text-white mt-3">
                {totalSearches}
              </div>
            </div>

            {/* Stat 2: Saved Patents */}
            <div className="p-6 rounded-2xl bg-white/[0.08] backdrop-blur-2xl border border-white/20 shadow-xl hover:bg-white/[0.12] hover:border-white/30 transition-all group">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-purple-200/80 tracking-wide uppercase">Saved Patents</span>
                <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-400/30 flex items-center justify-center text-emerald-300 group-hover:scale-110 transition-transform">
                  <Bookmark className="w-5 h-5" />
                </div>
              </div>
              <div className="text-3xl font-black font-mono text-white mt-3">
                {savedCount}
              </div>
            </div>

            {/* Stat 3: Reports */}
            <div className="p-6 rounded-2xl bg-white/[0.08] backdrop-blur-2xl border border-white/20 shadow-xl hover:bg-white/[0.12] hover:border-white/30 transition-all group">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-purple-200/80 tracking-wide uppercase">Reports</span>
                <div className="w-10 h-10 rounded-xl bg-pink-500/20 border border-pink-400/30 flex items-center justify-center text-pink-300 group-hover:scale-110 transition-transform">
                  <FileText className="w-5 h-5" />
                </div>
              </div>
              <div className="text-3xl font-black font-mono text-white mt-3">
                {reportsCount}
              </div>
            </div>

            {/* Stat 4: Highest Similarity */}
            <div className="p-6 rounded-2xl bg-white/[0.08] backdrop-blur-2xl border border-white/20 shadow-xl hover:bg-white/[0.12] hover:border-white/30 transition-all group">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-purple-200/80 tracking-wide uppercase">Highest Similarity</span>
                <div className="w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-400/30 flex items-center justify-center text-amber-300 group-hover:scale-110 transition-transform">
                  <TrendingUp className="w-5 h-5" />
                </div>
              </div>
              <div className="text-3xl font-black font-mono text-white mt-3">
                {highestSim}%
              </div>
            </div>

          </div>

          {/* Recent Prior-Art Searches Glass Table Container */}
          <div className="p-7 rounded-3xl bg-white/[0.08] backdrop-blur-2xl border border-white/20 shadow-2xl space-y-5">
            
            <div className="flex items-center justify-between pb-3 border-b border-white/10">
              <div>
                <h3 className="text-lg font-extrabold text-white tracking-tight">Recent Prior-Art Searches</h3>
              </div>
              <Link
                href="/history"
                className="text-xs font-semibold text-indigo-300 hover:text-white transition-colors flex items-center gap-1.5"
              >
                <span>View All</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>

            <div className="overflow-x-auto">
              {history.length === 0 ? (
                <div className="py-10 text-center space-y-3">
                  <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center mx-auto text-indigo-300">
                    <Search className="w-6 h-6" />
                  </div>
                  <p className="text-xs text-purple-200/70 font-medium">No prior-art searches performed yet.</p>
                  <Link
                    href="/search"
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-bold text-xs shadow-md shadow-indigo-500/20 transition-all"
                  >
                    <span>Start Your First Search</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              ) : (
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-white/10 text-purple-200/70 font-mono text-[10px] uppercase tracking-wider">
                      <th className="pb-3 pr-4 font-bold">Invention Title</th>
                      <th className="pb-3 pr-4 font-bold">Domain</th>
                      <th className="pb-3 pr-4 font-bold">Date</th>
                      <th className="pb-3 pr-4 text-right font-bold">Highest Sim</th>
                      <th className="pb-3 text-right font-bold whitespace-nowrap">Risk Level</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.06]">
                    {history.slice(0, 5).map((item) => (
                      <tr key={item.id} className="hover:bg-white/[0.06] transition-colors group">
                        <td className="py-4 font-bold text-white max-w-[280px] sm:max-w-md truncate pr-4" title={item.invention_title}>
                          <Link href={`/search/${item.id}`} className="group-hover:text-indigo-300 transition-colors">
                            {item.invention_title}
                          </Link>
                        </td>
                        <td className="py-4 text-purple-200/90 font-semibold whitespace-nowrap pr-4">{item.domain}</td>
                        <td className="py-4 text-purple-200/70 font-mono text-[11px] whitespace-nowrap pr-4">{formatDate(item.created_at)}</td>
                        <td className="py-4 text-right font-mono font-extrabold text-cyan-300 text-sm whitespace-nowrap pr-4">
                          {item.highest_similarity}%
                        </td>
                        <td className="py-4 text-right whitespace-nowrap flex justify-end">
                          <RiskBadge level={item.risk_level} size="sm" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

          </div>

          {/* Bottom Row — Quick Actions & Recharts Similarity Chart */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            
            {/* Quick Actions Card */}
            <div className="lg:col-span-5 p-7 rounded-3xl bg-white/[0.08] backdrop-blur-2xl border border-white/20 shadow-2xl space-y-4">
              <h3 className="text-base font-extrabold text-white tracking-tight">Quick Actions</h3>
              
              <div className="space-y-3">
                <Link
                  href="/search"
                  className="w-full py-3.5 px-5 rounded-2xl bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-500 hover:scale-[1.02] active:scale-98 text-white text-xs font-bold transition-all shadow-lg shadow-indigo-500/30 border border-white/20 flex items-center justify-center gap-2"
                >
                  <PlusCircle className="w-4 h-4 text-white" />
                  <span>Start New Search</span>
                </Link>

                <Link
                  href="/history"
                  className="w-full py-3.5 px-5 rounded-2xl bg-white/10 hover:bg-white/15 text-white text-xs font-semibold transition-all border border-white/20 flex items-center justify-start gap-3 backdrop-blur-md"
                >
                  <History className="w-4 h-4 text-purple-300" />
                  <span>View Search History</span>
                </Link>

                <Link
                  href="/saved"
                  className="w-full py-3.5 px-5 rounded-2xl bg-white/10 hover:bg-white/15 text-white text-xs font-semibold transition-all border border-white/20 flex items-center justify-start gap-3 backdrop-blur-md"
                >
                  <Bookmark className="w-4 h-4 text-purple-300" />
                  <span>View Saved Patents</span>
                </Link>
              </div>
            </div>

            {/* Recent Similarity Scores Bar Chart */}
            <div className="lg:col-span-7 p-7 rounded-3xl bg-white/[0.08] backdrop-blur-2xl border border-white/20 shadow-2xl space-y-4">
              <h3 className="text-base font-extrabold text-white tracking-tight">Recent Similarity Scores</h3>
              
              <div className="h-48 pt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={displayChartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="bar-gradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#818cf8" stopOpacity={0.9} />
                        <stop offset="100%" stopColor="#c084fc" stopOpacity={0.7} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
                    <XAxis dataKey="title" stroke="rgba(255,255,255,0.6)" fontSize={10} tickLine={false} />
                    <YAxis stroke="rgba(255,255,255,0.6)" fontSize={10} domain={[0, 100]} unit="%" tickLine={false} />
                    <Tooltip
                      contentStyle={{
                        background: "rgba(13, 15, 43, 0.9)",
                        borderColor: "rgba(255, 255, 255, 0.2)",
                        borderRadius: "12px",
                        fontSize: "11px",
                        color: "#fff",
                        backdropFilter: "blur(10px)"
                      }}
                    />
                    <Bar dataKey="score" fill="url(#bar-gradient)" radius={[8, 8, 0, 0]} barSize={40} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

          </div>

        </div>
      </main>
    </div>
  );
}
