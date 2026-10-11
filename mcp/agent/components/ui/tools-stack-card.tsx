"use client";

import { cn } from "@/lib/utils";
import { animate, motion } from "framer-motion";
import { useEffect, useMemo } from "react";

// Spark platform capabilities — rendered as glass orbs with the same
// sequential-bounce + sweeping-beam + sparkle animation from
// myworkassistant's ToolsStackCard.
//
// Middle slot (the largest 64px ring orb) swapped from the
// gold `bolt` glyph to the actual Phantom logo (/logo.svg, same asset
// as the sidebar). Same orb shell, same sequential-bounce animation,
// same ring; only the inner content differs. The 4 outer orbs keep
// their material-symbol glyphs unchanged.
type ToolItem =
  | { key: string; kind: "icon"; icon: string; color: string; size: string }
  | { key: string; kind: "logo"; logoSrc: string; logoSize: number };

const logoItems: ToolItem[] = [
  { key: "agents", kind: "icon", icon: "smart_toy", color: "#60a5fa", size: "text-lg" },
  { key: "memory", kind: "icon", icon: "memory", color: "#a78bfa", size: "text-xl" },
  { key: "phantom", kind: "logo", logoSrc: "/logo.svg", logoSize: 44 },
  { key: "observe", kind: "icon", icon: "monitoring", color: "#34d399", size: "text-xl" },
  { key: "mcp", kind: "icon", icon: "api", color: "#f472b6", size: "text-lg" },
];

type SparkleSpec = {
  left: number;
  top: number;
  dx: number;
  dy: number;
  duration: number;
  delay: number;
  opacity: number;
};

export function ToolsStackCard({ animationsEnabled = true }: { animationsEnabled?: boolean }) {
  const sequence = useMemo(
    () =>
      logoItems.map((_, index) => [
        `.tool-pill-${index}`,
        { scale: [1, 1.1, 1], transform: ["translateY(0px)", "translateY(-4px)", "translateY(0px)"] },
        { duration: 0.8 },
      ]) as Parameters<typeof animate>[0],
    []
  );

  useEffect(() => {
    if (!animationsEnabled) return;

    const controls = animate(sequence, {
      repeat: Infinity,
      repeatDelay: 1,
    });

    return () => { controls.stop(); };
  }, [animationsEnabled, sequence]);

  return <Skeleton animationsEnabled={animationsEnabled} />;
}

const Skeleton = ({ animationsEnabled }: { animationsEnabled: boolean }) => {
  return (
    <div className="relative flex h-[11rem] w-full items-center justify-center overflow-hidden md:h-[12rem]">
      <div className="relative z-20 flex shrink-0 items-center justify-center gap-2">
        {logoItems.map((item, index) => (
          <Container
            key={item.key}
            className={cn(
              `tool-pill-${index}`,
              index === 0 && "h-9 w-9",
              index === 1 && "h-12 w-12",
              index === 2 && "h-16 w-16 ring-1 ring-fuchsia-200/25",
              index === 3 && "h-12 w-12",
              index === 4 && "h-9 w-9"
            )}
          >
            {item.kind === "logo" ? (
              /* Phantom logo inside the middle orb. Same
                 SVG asset as the sidebar's PhantomLogo (animation
                 lives inside the SVG file itself, not the wrapper),
                 sized to fill the 64px ring with the visual weight
                 of the glyph it replaced. */
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={item.logoSrc}
                alt="Phantom logo"
                width={item.logoSize}
                height={item.logoSize}
                style={{ display: "block" }}
              />
            ) : (
              <span
                className={cn("material-symbols-outlined opacity-95", item.size)}
                style={{ color: item.color, fontVariationSettings: "'FILL' 1" }}
              >
                {item.icon}
              </span>
            )}
          </Container>
        ))}
      </div>

      {/* Sweeping cyan beam */}
      <motion.div
        className="absolute top-8 left-1/2 z-40 h-40 w-px bg-gradient-to-b from-transparent via-cyan-400/80 to-transparent"
        animate={animationsEnabled ? { x: [-150, -40, 80, 150], opacity: [0, 1, 1, 0] } : { x: 0, opacity: 0.45 }}
        transition={animationsEnabled ? { duration: 6.2, ease: "linear", repeat: Infinity, repeatDelay: 0.4 } : { duration: 0 }}
      >
        <div className="absolute -left-10 top-1/2 h-32 w-12 -translate-y-1/2">
          <Sparkles animationsEnabled={animationsEnabled} />
        </div>
      </motion.div>
    </div>
  );
};

const Sparkles = ({ animationsEnabled }: { animationsEnabled: boolean }) => {
  const sparkles = useMemo<SparkleSpec[]>(
    () =>
      Array.from({ length: 12 }, () => ({
        left: Math.random() * 100,
        top: Math.random() * 100,
        dx: Math.random() * 10 - 5,
        dy: Math.random() * 10 - 5,
        duration: Math.random() * 2 + 4,
        delay: Math.random() * 1.5,
        opacity: Math.random() * 0.55 + 0.2,
      })),
    []
  );

  return (
    <div className="absolute inset-0">
      {sparkles.map((sparkle, i) => (
        animationsEnabled ? (
          <motion.span
            key={`star-${i}`}
            animate={{
              x: [0, sparkle.dx, 0],
              y: [0, sparkle.dy, 0],
              opacity: [sparkle.opacity, 1, 0],
              scale: [1, 1.2, 0],
            }}
            transition={{
              duration: sparkle.duration,
              delay: sparkle.delay,
              repeat: Infinity,
              ease: "linear",
            }}
            style={{
              position: "absolute",
              top: `${sparkle.top}%`,
              left: `${sparkle.left}%`,
              width: "2px",
              height: "2px",
              borderRadius: "50%",
              zIndex: 1,
            }}
            className="inline-block bg-white"
          />
        ) : (
          <span
            key={`star-${i}`}
            style={{
              position: "absolute",
              top: `${sparkle.top}%`,
              left: `${sparkle.left}%`,
              width: "2px",
              height: "2px",
              borderRadius: "50%",
              zIndex: 1,
              opacity: sparkle.opacity,
            }}
            className="inline-block bg-white"
          />
        )
      ))}
    </div>
  );
};

function Container({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "flex h-16 w-16 items-center justify-center rounded-full bg-[rgba(248,248,248,0.03)] shadow-[0px_0px_8px_0px_rgba(248,248,248,0.28)_inset,0px_32px_24px_-16px_rgba(0,0,0,0.45)]",
        className
      )}
    >
      {children}
    </div>
  );
}
