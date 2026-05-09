/**
 * FullPageView — Sprint 192: Shared layout for full-page admin/settings views.
 *
 * Section sidebar (220px) + content area pattern.
 * Used by SystemAdminView, OrgAdminView, SettingsView.
 */
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft } from "lucide-react";
import { useId } from "react";
import { viewEnter } from "@/lib/animations";
import { useReducedMotion, motionSafe } from "@/hooks/useReducedMotion";

export interface FullPageTab {
  id: string;
  label: string;
  icon: React.ReactNode;
}

interface FullPageViewProps {
  title: string;
  subtitle?: string;
  icon: React.ReactNode;
  tabs: FullPageTab[];
  activeTab: string;
  onTabChange: (id: string) => void;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function FullPageView({
  title,
  subtitle,
  icon,
  tabs,
  activeTab,
  onTabChange,
  onClose,
  children,
  footer,
}: FullPageViewProps) {
  const reduced = useReducedMotion();
  const titleId = useId();

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      {/* Section Sidebar */}
      <div className="shrink-0 w-full md:w-[220px] max-h-[46dvh] md:max-h-none bg-surface-secondary border-b md:border-b-0 md:border-r border-border flex flex-col">
        {/* Header */}
        <div className="px-4 pt-4 md:pt-5 pb-3 md:pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-[var(--accent)]">{icon}</span>
            <div className="min-w-0">
              <h2 id={titleId} className="text-sm font-semibold text-text truncate">{title}</h2>
              {subtitle && (
                <p className="text-xs text-text-tertiary truncate mt-0.5">{subtitle}</p>
              )}
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav
          className="flex md:block flex-none md:flex-1 gap-1 md:space-y-0.5 px-3 md:px-2 overflow-x-auto md:overflow-x-visible md:overflow-y-auto"
          aria-label={title}
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`flex shrink-0 md:shrink items-center gap-2.5 md:w-full px-3 py-2 rounded-lg text-sm transition-colors ${
                activeTab === tab.id
                  ? "bg-[var(--accent)]/10 text-[var(--accent)] font-medium md:border-l-2 border-[var(--accent)] md:-ml-[2px] md:pl-[calc(0.75rem+2px)]"
                  : "text-text-secondary hover:bg-surface-tertiary hover:text-text"
              }`}
              aria-current={activeTab === tab.id ? "page" : undefined}
            >
              {tab.icon}
              <span className="truncate">{tab.label}</span>
            </button>
          ))}
        </nav>

        {/* Footer: Back to chat */}
        <div className="p-3 border-t border-border">
          {footer}
          <button
            onClick={onClose}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-text-secondary hover:bg-surface-tertiary hover:text-text transition-colors"
          >
            <ArrowLeft size={14} />
            Quay lại trò chuyện
          </button>
        </div>
      </div>

      {/* Content Area */}
      <main
        className="flex-1 min-w-0 overflow-y-auto"
        aria-labelledby={titleId}
        data-testid="full-page-content"
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            variants={motionSafe(reduced, viewEnter)}
            initial={reduced ? false : "hidden"}
            animate="visible"
            exit={reduced ? undefined : "exit"}
            className="p-4 md:p-6 max-w-full md:max-w-7xl"
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
