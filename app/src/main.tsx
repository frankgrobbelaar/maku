import "@fontsource-variable/manrope";
import "@fontsource-variable/geist-mono";
import "./styles/global.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app";
import { savedScheme, showScheme, startingScheme } from "./lib/look";

// The scheme the shell's script put on the page before its first frame (lib/scheme-script.js;
// Velvet outside Maku's window), then the one the shell keeps, should they differ.
showScheme(startingScheme());
savedScheme().then(showScheme, () => {});

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element.");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
