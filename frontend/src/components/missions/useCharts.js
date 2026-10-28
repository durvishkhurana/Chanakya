"use client";

import { useEffect, useState } from "react";

let loading;

/** Loads the SVG chart helper (public/charts.js) once and returns window.Charts when it is ready. */
export default function useCharts() {
  const [charts, setCharts] = useState(() => (typeof window !== "undefined" ? window.Charts || null : null));
  useEffect(() => {
    if (window.Charts) { setCharts(window.Charts); return; }
    loading ||= new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/charts.js";
      script.onload = () => resolve(window.Charts);
      script.onerror = reject;
      document.head.appendChild(script);
    });
    loading.then(setCharts).catch(() => setCharts(null));
  }, []);
  return charts;
}
