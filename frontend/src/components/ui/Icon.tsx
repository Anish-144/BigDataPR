import type { SVGProps } from "react";
import { 
  LayoutDashboard, FlaskConical, PlayCircle, Activity, ShieldCheck, 
  AlertTriangle, Lock, Database, GitCompare, MessageSquare, GitMerge, 
  FileText, Check, X, AlertCircle, Info, Minus, Circle, Diamond, 
  HelpCircle, RefreshCw, ChevronLeft, ChevronRight, ChevronDown, 
  Menu, ExternalLink, Download, Play, Square, Search, Table, 
  BarChart2, Sun, Moon, Monitor, Flag, Link as LinkIcon, 
  PanelLeftClose, PanelLeftOpen 
} from "lucide-react";

const LUCIDE_ICONS = {
  overview: LayoutDashboard,
  lab: FlaskConical,
  runs: PlayCircle,
  perf: Activity,
  quality: ShieldCheck,
  anomaly: AlertTriangle,
  security: Lock,
  sql: Database,
  compare: GitCompare,
  assistant: MessageSquare,
  pipeline: GitMerge,
  reports: FileText,
  check: Check,
  x: X,
  alert: AlertCircle,
  info: Info,
  minus: Minus,
  dot: Circle,
  diamond: Diamond,
  question: HelpCircle,
  refresh: RefreshCw,
  chevronLeft: ChevronLeft,
  chevronRight: ChevronRight,
  chevronDown: ChevronDown,
  menu: Menu,
  external: ExternalLink,
  download: Download,
  play: Play,
  stop: Square,
  search: Search,
  table: Table,
  chart: BarChart2,
  sun: Sun,
  moon: Moon,
  monitor: Monitor,
  flag: Flag,
  link: LinkIcon,
  collapse: PanelLeftClose,
  expand: PanelLeftOpen,
} as const;

export type IconName = keyof typeof LUCIDE_ICONS;

export function Icon({ name, size = 16, className, ...rest }: { name: IconName; size?: number } & Omit<SVGProps<SVGSVGElement>, "ref">) {
  const Comp = LUCIDE_ICONS[name];
  if (!Comp) return null;
  return <Comp size={size} className={className} strokeWidth={2} {...rest as any} />;
}
