/**
 * WorkspaceSelector — org switcher dropdown in sidebar.
 * Sprint 156: Org-first UI restructuring.
 *
 * ChatGPT Teams / Claude Teams-style workspace selector.
 * Shows current org with chevron dropdown when 2+ orgs available.
 * Static label when single org or multi-tenant disabled.
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, Check, Globe } from "lucide-react";
import { useOrgStore } from "@/stores/org-store";
import { useSettingsStore } from "@/stores/settings-store";
import { useDomainStore } from "@/stores/domain-store";
import { getOrgDisplayName, getOrgIcon } from "@/lib/org-config";
import { PERSONAL_ORG_ID } from "@/lib/constants";

export function WorkspaceSelector() {
  const {
    organizations,
    activeOrgId,
    multiTenantEnabled,
    setActiveOrg,
    activeOrg,
  } = useOrgStore();
  const { updateSettings } = useSettingsStore();
  const { setOrgFilter } = useDomainStore();

  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const currentOrg = activeOrg();
  const displayName = currentOrg
    ? getOrgDisplayName(currentOrg)
    : "Wiii Cá nhân";
  const effectiveOrgId = activeOrgId || PERSONAL_ORG_ID;
  const OrgIcon = getOrgIcon(effectiveOrgId);
  const hasMultipleOrgs = organizations.length > 1;

  // Outside-click close
  const handleClickOutside = useCallback(
    (e: MouseEvent) => {
      if (
        open &&
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    },
    [open],
  );

  useEffect(() => {
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [handleClickOutside]);

  // Escape key close
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  const handleSelect = (orgId: string) => {
    setActiveOrg(orgId === PERSONAL_ORG_ID ? null : orgId);
    // Sync to settings for persistence + auth headers
    updateSettings({
      organization_id: orgId === PERSONAL_ORG_ID ? null : orgId,
    });
    // Update domain filter based on org's allowed_domains
    const org = organizations.find((o) => o.id === orgId);
    setOrgFilter(org?.allowed_domains ?? []);
    setOpen(false);
  };

  // Non-interactive when multi-tenant disabled or single org
  if (!multiTenantEnabled || !hasMultipleOrgs) {
    return (
      <div
        className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-sm text-text-secondary"
        data-testid="workspace-selector"
        title={displayName}
      >
        {multiTenantEnabled ? (
          <OrgIcon size={15} className="shrink-0" />
        ) : (
          <Globe size={15} className="shrink-0" />
        )}
        <span className="truncate font-medium">{displayName}</span>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative" data-testid="workspace-selector">
      {/* Trigger */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full px-2 py-1.5 rounded-lg text-sm text-text-secondary hover:text-text hover:bg-surface-tertiary transition-colors"
        aria-label="Chọn không gian làm việc"
        aria-expanded={open}
        data-testid="workspace-selector-trigger"
        title={displayName}
      >
        <OrgIcon size={15} className="shrink-0" />
        <span className="flex-1 truncate text-left font-medium">
          {displayName}
        </span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 20 }}
          className="inline-flex shrink-0"
        >
          <ChevronDown size={14} />
        </motion.span>
      </button>

      {/* Dropdown */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -4 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute top-full left-0 right-0 mt-1 rounded-xl border border-border bg-surface shadow-lg z-50"
            role="listbox"
            aria-label="Danh sách không gian làm việc"
            data-testid="workspace-selector-dropdown"
          >
            <div className="py-1">
              {organizations.map((org) => {
                const orgDisplayName = getOrgDisplayName(org);
                const Icon = getOrgIcon(org.id);
                const isActive = org.id === effectiveOrgId;
                return (
                  <button
                    key={org.id}
                    onClick={() => handleSelect(org.id)}
                    role="option"
                    aria-selected={isActive}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors ${
                      isActive
                        ? "text-[var(--accent)] bg-[var(--accent-light)]"
                        : "text-text hover:bg-surface-secondary"
                    }`}
                  >
                    <Icon size={15} />
                    <span className="flex-1 text-left truncate">
                      {orgDisplayName}
                    </span>
                    {isActive && (
                      <Check size={14} className="text-[var(--accent)] shrink-0" />
                    )}
                  </button>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
