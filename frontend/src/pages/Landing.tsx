import { useState } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "../components/ui/Icon";

export default function Landing() {
  const [servicesOpen, setServicesOpen] = useState(false);

  return (
    <div className="min-h-screen bg-page text-ink flex flex-col font-sans relative selection:bg-accent/20 scroll-smooth">
      {/* Premium subtle dot grid background */}
      <div className="absolute inset-0 z-0 pointer-events-none opacity-[0.4]" style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, rgb(var(--line-strong)) 1px, transparent 0)', backgroundSize: '32px 32px' }}></div>
      
      {/* Top Navigation */}
      <header className="flex items-center justify-between px-8 py-5 sticky top-0 z-50 bg-page/80 backdrop-blur-xl border-b border-line/50 transition-all">
        <div className="flex items-center gap-2.5 group cursor-pointer">
          <div className="bg-accent-strong p-1.5 rounded-lg shadow-sm group-hover:scale-105 transition-transform">
            <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
              <path d="M16 2 4 7v8c0 7.5 5.1 13.4 12 15 6.9-1.6 12-7.5 12-15V7L16 2Z" fill="#fff" />
              <path d="M10 16.5l4 4 8-9" fill="none" stroke="rgb(var(--accent-strong))" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <span className="font-bold text-[17px] tracking-tight text-ink">AgentShield</span>
        </div>
        <div className="flex items-center gap-5">
          <div className="relative hidden sm:block">
            <button 
              onClick={() => setServicesOpen(!servicesOpen)}
              onBlur={() => setTimeout(() => setServicesOpen(false), 200)}
              className="flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink transition-colors"
            >
              Services <Icon name={servicesOpen ? "chevronDown" : "chevronRight"} size={14} className="opacity-70" />
            </button>
            <AnimatePresence>
              {servicesOpen && (
                <motion.div
                  initial={{ opacity: 0, y: 10, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 10, scale: 0.95 }}
                  transition={{ duration: 0.15 }}
                  className="absolute right-0 top-full mt-4 w-56 bg-surface border border-line rounded-xl shadow-xl overflow-hidden z-50 flex flex-col p-1.5 origin-top-right"
                >
                  <ServiceLink href="http://localhost:3000" label="Dashboard" sublabel="Frontend UI" icon="overview" />
                  <ServiceLink href="http://localhost:8000/docs" label="API Docs" sublabel="OpenAPI" icon="lab" />
                  <ServiceLink href="http://localhost:8080" label="Trino UI" sublabel="SQL Engine" icon="sql" />
                  <ServiceLink href="http://localhost:4040" label="Spark UI" sublabel="Structured Streaming" icon="chart" />
                  <ServiceLink href="http://localhost:9001" label="MinIO Console" sublabel="S3 Storage" icon="table" />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <Link to="/app" className="inline-flex items-center justify-center gap-2 h-9 px-5 rounded-full bg-ink text-surface text-sm font-medium hover:bg-ink/90 hover:scale-[1.02] transition-all shadow-sm">
            Open Workbench <Icon name="chevronRight" size={14} className="opacity-70" />
          </Link>
        </div>
      </header>

      <main className="flex-1 flex flex-col items-center justify-center px-6 lg:px-12 py-20 relative z-10">
        {/* Soft glow effects */}
        <div className="absolute top-1/4 left-1/4 w-[500px] h-[500px] bg-accent/10 rounded-full blur-[100px] -z-10 pointer-events-none mix-blend-multiply dark:mix-blend-screen" />
        <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[400px] bg-secondary/10 rounded-full blur-[100px] -z-10 pointer-events-none mix-blend-multiply dark:mix-blend-screen" />

        <div className="max-w-[1200px] w-full grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-20 items-center">
          
          {/* Left Hero Text */}
          <motion.div 
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
            className="flex flex-col gap-6 lg:col-span-6"
          >
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface border border-line shadow-sm w-max">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-strong"></span>
              </span>
              <span className="text-[11px] font-bold tracking-widest text-ink-2 uppercase">Big Data × AI Reliability</span>
            </div>
            
            <h1 className="text-5xl sm:text-6xl lg:text-[4rem] font-extrabold tracking-tighter text-ink leading-[1.05]">
              Every agent run <br className="hidden sm:block" />
              <span className="text-transparent bg-clip-text bg-gradient-to-br from-accent-strong to-accent">leaves evidence.</span>
            </h1>
            
            <p className="text-lg text-ink-2 max-w-lg leading-relaxed mt-2 font-medium">
              Turn AI-agent telemetry into performance insights, anomaly signals, regression evidence, and actionable security investigations.
            </p>
            
            <div className="flex flex-wrap items-center gap-4 mt-6">
              <Link to="/app" className="inline-flex items-center justify-center h-12 px-8 rounded-full bg-accent-strong text-white text-base font-semibold hover:bg-accent-strong/90 hover:shadow-lg hover:shadow-accent/20 hover:-translate-y-0.5 transition-all">
                Explore the Workbench
              </Link>
              <a href="#architecture" className="inline-flex items-center justify-center h-12 px-8 rounded-full bg-surface border border-line text-ink text-base font-medium hover:bg-surface-2 hover:border-line-strong transition-all">
                See How It Works
              </a>
            </div>
            
            <div className="mt-12 pt-8 border-t border-line/60">
              <p className="text-xs text-muted font-medium tracking-wide uppercase mb-3">Powered By</p>
              <div className="flex flex-wrap gap-x-6 gap-y-3 text-sm font-semibold text-ink-2">
                <span className="flex items-center gap-1.5"><Icon name="runs" size={14} className="text-accent" /> Kafka</span>
                <span className="flex items-center gap-1.5"><Icon name="chart" size={14} className="text-warning" /> Spark Streaming</span>
                <span className="flex items-center gap-1.5"><Icon name="sql" size={14} className="text-secondary" /> Apache Iceberg</span>
                <span className="flex items-center gap-1.5"><Icon name="pipeline" size={14} className="text-good" /> Trino</span>
              </div>
            </div>
          </motion.div>

          {/* Right Pipeline Illustration */}
          <motion.div 
            initial={{ opacity: 0, scale: 0.95, filter: "blur(10px)" }}
            animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
            transition={{ duration: 0.9, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="lg:col-span-6 relative w-full h-[540px] flex items-center justify-center"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-surface to-surface-2 border border-line rounded-[2rem] shadow-xl overflow-hidden">
              {/* Decorative inner elements */}
              <div className="absolute top-0 left-1/2 -translate-x-1/2 w-3/4 h-px bg-gradient-to-r from-transparent via-accent/30 to-transparent" />
              <div className="absolute -left-20 -top-20 w-40 h-40 bg-accent/5 rounded-full blur-2xl" />
              
              <div className="h-full w-full p-8 flex flex-col justify-between relative z-10">
                <PipelineNode title="Generator" subtitle="Workloads & Prompts" icon="lab" active />
                <PipelineConnection />
                <PipelineNode title="Kafka" subtitle="Event Streaming" icon="runs" active />
                <PipelineConnection />
                
                <div className="flex justify-between items-center gap-4">
                  <div className="flex-1">
                    <PipelineNode title="Spark" subtitle="Structured Streaming" icon="chart" active />
                  </div>
                  <div className="w-12 h-px bg-line-strong relative">
                    <motion.div className="absolute top-1/2 left-0 w-2 h-2 -mt-1 rounded-full bg-warning" animate={{ left: ["0%", "100%"] }} transition={{ repeat: Infinity, duration: 1.5, ease: "linear" }} />
                  </div>
                  <div className="flex-1">
                    <PipelineNode title="Detectors" subtitle="Anomaly Rules" icon="anomaly" warning />
                  </div>
                </div>
                
                <PipelineConnection />
                <PipelineNode title="Lakehouse" subtitle="Iceberg / Trino" icon="sql" active />
                <PipelineConnection />
                <PipelineNode title="AgentShield" subtitle="Analytics Workbench" icon="overview" active highlight />
              </div>
            </div>
          </motion.div>
        </div>
      </main>

      {/* Architecture Section */}
      <section id="architecture" className="w-full bg-surface-2 py-32 px-6 lg:px-12 border-t border-line relative z-10">
        <div className="max-w-[1200px] mx-auto flex flex-col gap-16">
          <div className="text-center max-w-3xl mx-auto flex flex-col gap-4">
            <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-ink">How AgentShield Works</h2>
            <p className="text-lg text-ink-2 leading-relaxed">
              A purpose-built Big Data streaming architecture designed to capture, process, and analyze massive volumes of AI telemetry in near real-time.
            </p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <FeatureCard 
              icon="lab" 
              title="1. Workload Generator" 
              desc="Simulates synthetic, deterministic AI agent workloads with controlled fault injection to generate realistic telemetry." 
            />
            <FeatureCard 
              icon="runs" 
              title="2. Apache Kafka" 
              desc="Provides durable, high-throughput event streaming, acting as a buffer for unpredictable spikes in agent telemetry." 
            />
            <FeatureCard 
              icon="chart" 
              title="3. Spark Streaming" 
              desc="Ingests events via micro-batches, validates schemas, and writes structured records into the Bronze and Silver lakehouse layers." 
            />
            <FeatureCard 
              icon="sql" 
              title="4. Iceberg on MinIO" 
              desc="Parquet data is managed by Apache Iceberg on MinIO (S3-compatible), offering ACID transactions and scalable storage." 
            />
            <FeatureCard 
              icon="anomaly" 
              title="5. ML Detectors" 
              desc="Asynchronous Isolation Forests and heuristic rules consume Trino data to score runs for behavioral anomalies." 
            />
            <FeatureCard 
              icon="overview" 
              title="6. Trino & React" 
              desc="Trino executes distributed SQL analytics served through FastAPI to this polished React observability workbench." 
            />
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="w-full py-32 px-6 text-center bg-page relative z-10">
        <h2 className="text-4xl md:text-5xl font-extrabold tracking-tight text-ink mb-8 leading-tight">
          Go beyond the dashboard. <br/>
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-accent-strong to-accent">Follow the evidence.</span>
        </h2>
        <Link to="/app" className="inline-flex items-center justify-center h-14 px-10 rounded-full bg-ink text-surface text-lg font-semibold hover:bg-ink/90 hover:shadow-xl hover:shadow-ink/20 hover:-translate-y-1 transition-all">
          Open AgentShield Workbench
        </Link>
      </section>
    </div>
  );
}

function FeatureCard({ icon, title, desc }: any) {
  return (
    <div className="flex flex-col gap-4 p-6 rounded-2xl bg-surface border border-line shadow-sm hover:shadow-md transition-shadow">
      <div className="w-12 h-12 rounded-xl bg-accent/10 flex items-center justify-center text-accent-strong">
        <Icon name={icon} size={24} strokeWidth={2} />
      </div>
      <div>
        <h3 className="text-lg font-bold text-ink mb-2 tracking-tight">{title}</h3>
        <p className="text-sm text-ink-2 leading-relaxed">{desc}</p>
      </div>
    </div>
  );
}

function PipelineNode({ title, subtitle, icon, active, warning, highlight }: any) {
  return (
    <div className={`flex items-center gap-4 p-4 rounded-xl border bg-surface relative z-10 transition-all duration-300 shadow-sm
      ${highlight ? 'border-accent/40 shadow-accent/10 ring-1 ring-accent/10' : warning ? 'border-warning/30 shadow-warning/5' : 'border-line'}
    `}>
      <div className={`p-2.5 rounded-lg flex items-center justify-center
        ${highlight ? 'bg-accent text-white shadow-md shadow-accent/20' : warning ? 'bg-warning/10 text-warning-ink' : 'bg-surface-2 text-ink-2'}
      `}>
        <Icon name={icon} size={20} strokeWidth={2.5} />
      </div>
      <div>
        <div className={`font-bold text-[15px] leading-tight ${highlight ? 'text-accent-strong' : 'text-ink'}`}>{title}</div>
        <div className="text-[13px] font-medium text-muted mt-0.5">{subtitle}</div>
      </div>
      
      {active && !warning && !highlight && (
        <div className="absolute right-4 top-1/2 -translate-y-1/2 flex gap-1">
           <motion.div className="w-1 h-1 rounded-full bg-accent" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ duration: 1.5, repeat: Infinity, delay: 0 }} />
           <motion.div className="w-1 h-1 rounded-full bg-accent" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ duration: 1.5, repeat: Infinity, delay: 0.2 }} />
           <motion.div className="w-1 h-1 rounded-full bg-accent" animate={{ opacity: [0.2, 1, 0.2] }} transition={{ duration: 1.5, repeat: Infinity, delay: 0.4 }} />
        </div>
      )}
    </div>
  );
}

function PipelineConnection() {
  return (
    <div className="flex justify-center -my-3 relative z-0">
      <div className="w-[1.5px] h-8 bg-gradient-to-b from-line-strong/30 via-line-strong to-line-strong/30 relative overflow-hidden">
        <motion.div 
          className="absolute inset-0 bg-accent w-full"
          initial={{ y: "-100%" }}
          animate={{ y: "100%" }}
          transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }}
        />
      </div>
    </div>
  );
}

function ServiceLink({ href, label, sublabel, icon }: any) {
  return (
    <a 
      href={href} 
      target="_blank" 
      rel="noreferrer"
      className="flex items-center gap-3 p-2 rounded-lg hover:bg-surface-2 transition-colors group"
    >
      <div className="p-1.5 rounded-md bg-surface border border-line text-ink-2 group-hover:text-accent-strong group-hover:border-accent/30 transition-colors">
        <Icon name={icon} size={16} />
      </div>
      <div className="flex flex-col">
        <span className="text-[13px] font-semibold text-ink group-hover:text-accent-strong transition-colors leading-tight">{label}</span>
        <span className="text-[11px] font-medium text-muted">{sublabel}</span>
      </div>
      <Icon name="external" size={12} className="ml-auto opacity-0 group-hover:opacity-100 text-accent transition-opacity" />
    </a>
  );
}
