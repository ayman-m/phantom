"use client";

import { useCallback, useEffect, useRef, useState, type RefCallback } from "react";

const BOTTOM_THRESHOLD_PX = 24;

export interface UseAutoScrollOptions {
  isStreaming: boolean;
  contentKey: unknown;
}

export interface UseAutoScrollResult {
  containerRef: RefCallback<HTMLDivElement>;
  endRef: RefCallback<HTMLDivElement>;
  showJumpToBottom: boolean;
  scrollToBottom: () => void;
}

export function useAutoScroll({
  isStreaming,
  contentKey,
}: UseAutoScrollOptions): UseAutoScrollResult {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [endElement, setEndElement] = useState<HTMLDivElement | null>(null);
  const [isAutoScrollEnabled, setIsAutoScrollEnabled] = useState(true);

  // Refs to hold latest values for use inside stable callbacks
  const containerRef_ = useRef(container);
  const endElementRef_ = useRef(endElement);
  const setIsAutoScrollEnabledRef = useRef(setIsAutoScrollEnabled);
  containerRef_.current = container;
  endElementRef_.current = endElement;

  const updateAutoScrollState = useCallback(() => {
    const c = containerRef_.current;
    if (!c) return;
    const distanceFromBottom = c.scrollHeight - c.clientHeight - c.scrollTop;
    setIsAutoScrollEnabledRef.current(distanceFromBottom <= BOTTOM_THRESHOLD_PX);
  }, []);

  const scrollToBottom = useCallback(() => {
    const end = endElementRef_.current;
    const c = containerRef_.current;
    if (typeof end?.scrollIntoView === "function") {
      end.scrollIntoView({ behavior: "smooth", block: "end" });
    } else if (c) {
      c.scrollTop = c.scrollHeight;
    }
    setIsAutoScrollEnabledRef.current(true);
  }, []);

  useEffect(() => {
    if (!container) return;

    updateAutoScrollState();
    container.addEventListener("scroll", updateAutoScrollState, { passive: true });

    return () => {
      container.removeEventListener("scroll", updateAutoScrollState);
    };
  }, [container, updateAutoScrollState]);

  useEffect(() => {
    if (!isAutoScrollEnabled) return;
    scrollToBottom();
  }, [contentKey, isAutoScrollEnabled, scrollToBottom]);

  const containerRef = useCallback<RefCallback<HTMLDivElement>>((node) => {
    setContainer(node);
  }, []);

  const endRef = useCallback<RefCallback<HTMLDivElement>>((node) => {
    setEndElement(node);
  }, []);

  return {
    containerRef,
    endRef,
    showJumpToBottom: isStreaming && !isAutoScrollEnabled,
    scrollToBottom,
  };
}
