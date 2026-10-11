"use client";

import { cn } from "@/lib/utils";
import { createNoise3D } from "simplex-noise";
import React, { useEffect, useRef, useState } from "react";

type WavyBackgroundProps = {
  children?: React.ReactNode;
  className?: string;
  containerClassName?: string;
  colors?: string[];
  waveWidth?: number;
  backgroundFill?: string;
  blur?: number;
  speed?: "slow" | "fast";
  waveOpacity?: number;
};

export function WavyBackground({
  children,
  className,
  containerClassName,
  colors,
  waveWidth,
  backgroundFill,
  blur = 10,
  speed = "fast",
  waveOpacity = 0.5,
  ...props
}: WavyBackgroundProps & Omit<React.HTMLAttributes<HTMLDivElement>, "children">) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationFrameRef = useRef<number>(0);

  const getSpeed = () => {
    switch (speed) {
      case "slow":
        return 0.001;
      case "fast":
        return 0.002;
      default:
        return 0.001;
    }
  };

  const waveColors = colors ?? ["#38bdf8", "#818cf8", "#c084fc", "#e879f9", "#22d3ee"];

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const noise = createNoise3D();
    let width = 0;
    let height = 0;
    let noiseTime = 0;

    const resize = () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
      ctx.filter = `blur(${blur}px)`;
    };

    const drawWave = (waveCount: number) => {
      noiseTime += getSpeed();
      for (let i = 0; i < waveCount; i += 1) {
        ctx.beginPath();
        ctx.lineWidth = waveWidth || 50;
        ctx.strokeStyle = waveColors[i % waveColors.length];
        for (let x = 0; x < width; x += 5) {
          const y = noise(x / 800, 0.3 * i, noiseTime) * 100;
          if (x === 0) {
            ctx.moveTo(x, y + height * 0.5);
          } else {
            ctx.lineTo(x, y + height * 0.5);
          }
        }
        ctx.stroke();
        ctx.closePath();
      }
    };

    const render = () => {
      ctx.fillStyle = backgroundFill || "black";
      ctx.globalAlpha = waveOpacity;
      ctx.fillRect(0, 0, width, height);
      drawWave(5);
      animationFrameRef.current = requestAnimationFrame(render);
    };

    resize();
    render();

    window.addEventListener("resize", resize);
    return () => {
      cancelAnimationFrame(animationFrameRef.current);
      window.removeEventListener("resize", resize);
    };
  }, [backgroundFill, blur, speed, waveColors, waveOpacity, waveWidth]);

  const [isSafari, setIsSafari] = useState(false);
  useEffect(() => {
    setIsSafari(
      typeof window !== "undefined" && navigator.userAgent.includes("Safari") && !navigator.userAgent.includes("Chrome")
    );
  }, []);

  return (
    <div className={cn("relative flex h-screen flex-col items-center justify-center overflow-hidden", containerClassName)}>
      <canvas
        className="absolute inset-0 z-0"
        ref={canvasRef}
        id="canvas"
        style={{ ...(isSafari ? { filter: `blur(${blur}px)` } : {}) }}
      />
      <div className={cn("relative z-10", className)} {...props}>
        {children}
      </div>
    </div>
  );
}
