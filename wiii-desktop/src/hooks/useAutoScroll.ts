/**
 * Auto-scroll hook — scrolls to bottom during streaming,
 * pauses when user scrolls up.
 * Sprint 81: Expose isAtBottom for scroll-to-bottom FAB.
 * Sprint 104: Slight delay for animation settle before smooth scroll.
 */
import { useEffect, useRef, useCallback, useState } from "react";

export function useAutoScroll(dependency: unknown) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef(false);
  const [isAtBottom, setIsAtBottom] = useState(true);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    if (containerRef.current) {
      containerRef.current.scrollTo({
        top: containerRef.current.scrollHeight,
        behavior,
      });
      isUserScrolledUp.current = false;
      setIsAtBottom(true);
    }
  }, []);

  // Auto-scroll when dependency changes (new content)
  // Slight delay (50ms) lets message entry animations settle before scrolling
  useEffect(() => {
    if (containerRef.current && !isUserScrolledUp.current) {
      const timer = setTimeout(() => {
        if (containerRef.current) {
          containerRef.current.scrollTo({
            top: containerRef.current.scrollHeight,
            behavior: "smooth",
          });
        }
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [dependency]);

  // Detect user scroll
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
      const scrolledUp = distanceFromBottom > 200;
      isUserScrolledUp.current = scrolledUp;
      setIsAtBottom(!scrolledUp);
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  return { containerRef, scrollToBottom, isAtBottom };
}
