/**
 * DomainSelector — inline domain picker dropdown.
 * Sprint 82: Claude Desktop-inspired model selector style.
 * Small pill button in ChatInput footer, dropdown opens upward.
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Anchor, ChevronUp, Check } from "lucide-react";
import { useDomainStore } from "@/stores/domain-store";
import { DOMAIN_ICONS, DOMAIN_LABELS } from "@/lib/domain-config";

interface DomainSelectorProps {
  /** Compact mode for inside-input placement — smaller, no chevron text */
  compact?: boolean;
}

export function DomainSelector({ compact: _compact }: DomainSelectorProps = {}) {
  const { activeDomainId, setActiveDomain, domains, getFilteredDomains } = useDomainStore();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Sprint 156: Use org-filtered domains
  const filteredDomains = getFilteredDomains();

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
    [open]
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

  const ActiveIcon = DOMAIN_ICONS[activeDomainId] || Anchor;
  const activeLabel =
    DOMAIN_LABELS[activeDomainId] ||
    domains.find((d) => d.id === activeDomainId)?.name_vi ||
    activeDomainId;

  // Sprint 156: Auto-hide when org has exactly 1 domain
  if (filteredDomains.length <= 1 && filteredDomains.length > 0) return null;

  // Build list: use org-filtered domains if available, fallback to all domains or hardcoded
  const sourceList = filteredDomains.length > 0 ? filteredDomains : domains;
  const domainList =
    sourceList.length > 0
      ? sourceList.map((d) => ({
          id: d.id,
          label: d.name_vi || DOMAIN_LABELS[d.id] || d.name,
          Icon: DOMAIN_ICONS[d.id] || Anchor,
        }))
      : Object.entries(DOMAIN_LABELS).map(([id, label]) => ({
          id,
          label,
          Icon: DOMAIN_ICONS[id] || Anchor,
        }));

  const handleSelect = (id: string) => {
    setActiveDomain(id);
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative">
      {/* Trigger pill */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs text-text-secondary hover:text-text hover:bg-surface-tertiary transition-colors"
        aria-label="Chọn lĩnh vực"
        aria-expanded={open}
        data-testid="domain-selector-trigger"
        data-wiii-id="domain-selector"
        data-wiii-synonyms="chọn domain,đổi domain,chọn lĩnh vực,đổi lĩnh vực,domain selector,lĩnh vực"
      >
        <ActiveIcon size={13} />
        <span>{activeLabel}</span>
        <motion.span
          animate={{ rotate: open ? 0 : 180 }}
          transition={{ type: "spring", stiffness: 300, damping: 20 }}
          className="inline-flex"
        >
          <ChevronUp size={12} />
        </motion.span>
      </button>

      {/* Dropdown (opens upward) */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 4 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute bottom-full left-0 mb-1 min-w-[180px] rounded-xl border border-border bg-surface shadow-lg domain-dropdown"
            role="listbox"
            aria-label="Danh sách lĩnh vực"
            data-testid="domain-selector-dropdown"
          >
            <div className="py-1">
              {domainList.map(({ id, label, Icon }) => {
                const isActive = id === activeDomainId;
                return (
                  <button
                    key={id}
                    onClick={() => handleSelect(id)}
                    role="option"
                    aria-selected={isActive}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors ${
                      isActive
                        ? "text-[var(--accent)] bg-[var(--accent-light)]"
                        : "text-text hover:bg-surface-secondary"
                    }`}
                  >
                    <Icon size={15} />
                    <span>{label}</span>
                    {isActive && (
                      <Check size={14} className="ml-auto text-[var(--accent)]" aria-label="Đã chọn" />
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
